"""Compare supported literal transcript markers and print review signals."""

import argparse
import re
from dataclasses import dataclass, field
from itertools import zip_longest
from pathlib import Path


TIME = r"(?:[0-9]{1,3}:)?[0-9]{1,2}:[0-5][0-9](?:[.,][0-9]{1,3})?"
LEADING_TIME = re.compile(rf"^[ \t]*(\[{TIME}\]|{TIME}(?=[ \t]|$))")
SPEAKER = (
    r"(?:Speaker|Lecturer|Instructor|Teacher|Student|Host|Guest|说话人|讲者|讲师|老师|"
    r"主持人|学生|同学|学员|听众|提问者)(?:[ \t_-]*[0-9]+)?"
)
LEADING_SPEAKER = re.compile(rf"^[ \t]*(\[{SPEAKER}\][ \t]*[:：]?|{SPEAKER}[ \t]*[:：])", re.IGNORECASE)
ORDERED_LIST = re.compile(r"^[ \t]*[0-9]{1,9}[.)][ \t]+")
FENCE = re.compile(r"^ {0,3}(?:(`{3,})(?!`)[^`]*|(~{3,}).*)$")
DATE = r"[0-9]{4}(?:-[0-9]{1,2}-[0-9]{1,2}|/[0-9]{1,2}/[0-9]{1,2}|年[0-9]{1,2}月[0-9]{1,2}[日号])"
NUMBER = r"[+−-]?(?:[0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?[%％]?"
BODY_TOKEN = re.compile(
    rf"(?P<inline_code>(?<!`)(?P<ticks>`+)(?!`).+?(?<!`)(?P=ticks)(?!`))"
    rf"|(?P<markers>\[{TIME}\])"
    rf"|(?P<numbers>(?<![A-Za-z0-9_.])(?:{DATE}|{NUMBER})(?![A-Za-z0-9_]|\.[0-9]))"
)
CATEGORIES = {
    "frontmatter": "Frontmatter prefix",
    "fenced_code": "Fenced code",
    "inline_code": "Inline code",
    "markers": "Timestamp or speaker marker",
    "numbers": "Numeric or date token",
}


@dataclass
class Anchor:
    line: int
    value: str


@dataclass
class Scan:
    anchors: dict[str, list[Anchor]] = field(default_factory=lambda: {key: [] for key in CATEGORIES})
    warnings: list[str] = field(default_factory=list)
    has_body: bool = False


def collect_prose(line: str, line_number: int, scan: Scan) -> None:
    line = ORDERED_LIST.sub("", line)
    for prefix in (LEADING_TIME, LEADING_SPEAKER):
        match = prefix.match(line)
        if match:
            scan.anchors["markers"].append(Anchor(line_number, match[1].rstrip()))
            line = line[match.end():]
    for match in BODY_TOKEN.finditer(line):
        scan.anchors[match.lastgroup].append(Anchor(line_number, match[0]))


def scan_transcript(transcript: str) -> Scan:
    scan = Scan()
    lines = transcript.splitlines(keepends=True)
    index = 0
    if lines and lines[0].removeprefix("\ufeff").rstrip(" \t\r\n") == "---":
        for end, line in enumerate(lines[1:], 1):
            if line.rstrip(" \t\r\n") == "---":
                scan.anchors["frontmatter"].append(Anchor(1, "".join(lines[:end + 1])))
                index = end + 1
                break
        else:
            scan.warnings.append("Possible frontmatter at line 1 has no closing --- delimiter.")

    scan.has_body = any(line.removeprefix("\ufeff").strip() for line in lines[index:])
    while index < len(lines):
        line = lines[index].rstrip("\r\n")
        if index == 0:
            line = line.removeprefix("\ufeff")
        opener = FENCE.fullmatch(line)
        if not opener:
            collect_prose(line, index + 1, scan)
            index += 1
            continue

        delimiter = opener[1] or opener[2]
        closer = re.compile(rf"^ {{0,3}}{delimiter[0]}{{{len(delimiter)},}}[ \t]*$")
        start = index
        index += 1
        while index < len(lines) and not closer.fullmatch(lines[index].rstrip("\r\n")):
            index += 1
        if index == len(lines):
            scan.warnings.append(f"Fence at line {start + 1} has no closing delimiter.")
        else:
            index += 1
        block = "".join(lines[start:index])
        if start == 0:
            block = block.removeprefix("\ufeff")
        scan.anchors["fenced_code"].append(Anchor(start + 1, block))
    return scan


def location(anchor: Anchor | None, show_value: bool) -> str:
    if anchor is None:
        return "no corresponding entry"
    if not show_value:
        return f"line {anchor.line}"
    sample = anchor.value if len(anchor.value) <= 60 else anchor.value[:57] + "..."
    return f"line {anchor.line} {sample!r}"


def compare(source_text: str, candidate_text: str) -> list[str]:
    source = scan_transcript(source_text)
    candidate = scan_transcript(candidate_text)
    findings = [f"Source has a boundary signal. {warning}" for warning in source.warnings]
    findings.extend(f"Candidate has a boundary signal. {warning}" for warning in candidate.warnings)
    if source.has_body and not candidate.has_body:
        findings.append("Candidate body is empty while the source body has content.")
    for key, label in CATEGORIES.items():
        pairs = zip_longest(source.anchors[key], candidate.anchors[key])
        for original, revised in pairs:
            if original is not None and revised is not None and original.value == revised.value:
                continue
            show_value = key not in {"frontmatter", "fenced_code"}
            left = location(original, show_value)
            right = location(revised, show_value)
            findings.append(f"{label} sequence differs (source {left}, candidate {right}).")
            break
    return findings


def read_utf8(path: Path, parser: argparse.ArgumentParser) -> str:
    try:
        # Byte reads retain line endings and a UTF-8 BOM for literal comparisons.
        return path.read_bytes().decode("utf-8")
    except (OSError, UnicodeError) as error:
        parser.error(f"Cannot read {path} as UTF-8 ({error}).")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare UTF-8 Markdown transcript files without writing them.",
        epilog=(
            "Checks a leading --- frontmatter prefix, top-level fences, single-line inline code, "
            "bracketed or line-leading timestamps, common speaker labels and standalone ASCII numeric "
            "or date tokens. Markdown ordered list prefixes are treated as formatting. Reports the "
            "first difference per category for review. A completed scan exits 0, even with findings."
        ),
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args()
    source = read_utf8(args.source, parser)
    candidate = read_utf8(args.candidate, parser)
    findings = compare(source, candidate)
    for finding in findings:
        print(finding)
    if not findings:
        print("No differences in supported markers.")
    print("Review source coverage, meaning and readability separately.")


if __name__ == "__main__":
    main()
