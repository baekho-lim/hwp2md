#!/usr/bin/env python3
"""fill_hwpx.py - Template Injection for HWPX files.

Reads a fill_plan.json and applies text replacements to an HWPX template,
preserving all original formatting (cell sizes, merge patterns, styles).

Uses direct XML manipulation (zipfile + lxml) to handle ALL text elements
including those inside table cells, which python-hwpx's iter_runs() misses.

Usage:
    python3 fill_hwpx.py <fill_plan.json>
    python3 fill_hwpx.py <fill_plan.json> -o <output.hwpx>
    python3 fill_hwpx.py --inspect <template.hwpx>          # List all text runs
    python3 fill_hwpx.py --inspect <template.hwpx> -q <text> # Search for text
"""

import json
import sys
import os
import argparse
import shutil
import tempfile
import zipfile
from pathlib import Path

try:
    from lxml import etree
except ImportError:
    import xml.etree.ElementTree as etree
    print("WARNING: lxml not installed, using stdlib xml.etree (less robust)", file=sys.stderr)

# HWPX namespaces
HWPX_NS = {
    "hp": "http://www.hancom.co.kr/hwpml/2011/paragraph",
    "hs": "http://www.hancom.co.kr/hwpml/2011/section",
    "hc": "http://www.hancom.co.kr/hwpml/2011/core",
    "hh": "http://www.hancom.co.kr/hwpml/2011/head",
    "ha": "http://www.hancom.co.kr/hwpml/2011/app",
    "hp10": "http://www.hancom.co.kr/hwpml/2016/paragraph",
}

HP_T_TAG = f"{{{HWPX_NS['hp']}}}t"
HP_TC_TAG = f"{{{HWPX_NS['hp']}}}tc"
HP_TBL_TAG = f"{{{HWPX_NS['hp']}}}tbl"
HP_P_TAG = f"{{{HWPX_NS['hp']}}}p"
HP_RUN_TAG = f"{{{HWPX_NS['hp']}}}run"
HP_SUBLIST_TAG = f"{{{HWPX_NS['hp']}}}subList"
HP_CELLADDR_TAG = f"{{{HWPX_NS['hp']}}}cellAddr"
HP_CELLSPAN_TAG = f"{{{HWPX_NS['hp']}}}cellSpan"

# Event logging for real-time UI
EVENT_FILE = os.environ.get("MD2HWP_EVENT_FILE")


def _log_event(event: dict) -> None:
    """Append event to JSONL file for SSE streaming."""
    if not EVENT_FILE:
        return
    with open(EVENT_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def _build_parent_map(tree) -> dict:
    """Build element-to-parent mapping for ancestor traversal."""
    parent_map = {}
    for parent in tree.iter():
        for child in parent:
            parent_map[child] = parent
    return parent_map


def _local_name(tag: str) -> str:
    """Extract local tag name from a namespaced XML tag."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _get_ancestor(elem, tag_local: str, parent_map: dict):
    """Walk up parent chain to find ancestor by local tag name."""
    current = parent_map.get(elem)
    while current is not None:
        tag = current.tag if isinstance(current.tag, str) else ""
        if _local_name(tag) == tag_local:
            return current
        current = parent_map.get(current)
    return None


def _find_cell_by_addr(tbl, col: int, row: int):
    """Find <hp:tc> by its <hp:cellAddr> coordinates."""
    for tc in tbl.findall(f".//{HP_TC_TAG}"):
        cell_addr = tc.find(f"./{HP_CELLADDR_TAG}")
        if cell_addr is None:
            continue
        try:
            col_addr = int(cell_addr.get("colAddr", "-1"))
            row_addr = int(cell_addr.get("rowAddr", "-1"))
        except ValueError:
            continue
        if col_addr == col and row_addr == row:
            return tc
    return None


def _set_cell_text(tc, text: str) -> None:
    """Set cell text, creating <hp:t> in first <hp:run> when absent."""
    run = tc.find(f".//{HP_RUN_TAG}")
    if run is None:
        sub_list = tc.find(f"./{HP_SUBLIST_TAG}")
        if sub_list is None:
            sub_list = etree.Element(HP_SUBLIST_TAG)
            tc.insert(0, sub_list)
        paragraph = sub_list.find(f"./{HP_P_TAG}")
        if paragraph is None:
            paragraph = etree.Element(HP_P_TAG)
            sub_list.append(paragraph)
        run = etree.Element(HP_RUN_TAG)
        paragraph.append(run)

    text_elem = run.find(f"./{HP_T_TAG}")
    if text_elem is None:
        text_elem = etree.Element(HP_T_TAG)
        run.append(text_elem)

    text_elem.text = text
    for child in list(text_elem):
        text_elem.remove(child)


def _clear_cell_except(tc, keep_elem, parent_map: dict) -> None:
    """Clear a cell except the run/paragraph containing keep_elem."""
    keep_run = _get_ancestor(keep_elem, "run", parent_map)
    keep_paragraph = _get_ancestor(keep_elem, "p", parent_map)

    for paragraph in list(tc.findall(f".//{HP_P_TAG}")):
        paragraph_parent = parent_map.get(paragraph)
        if paragraph is not keep_paragraph:
            if paragraph_parent is not None:
                paragraph_parent.remove(paragraph)
            continue

        for run in list(paragraph.findall(f"./{HP_RUN_TAG}")):
            if run is keep_run:
                continue
            paragraph.remove(run)

    if keep_run is not None:
        for text_elem in list(keep_run.findall(f"./{HP_T_TAG}")):
            if text_elem is keep_elem:
                continue
            keep_run.remove(text_elem)


def _get_table_index(tree, tbl) -> int:
    """Return ordinal table index in document tree."""
    for idx, candidate in enumerate(tree.findall(f".//{HP_TBL_TAG}")):
        if candidate is tbl:
            return idx
    return -1


def load_plan(plan_path: str) -> dict:
    """Load and validate fill_plan.json."""
    with open(plan_path, encoding="utf-8") as f:
        plan = json.load(f)

    required_keys = ["template_file", "output_file"]
    for key in required_keys:
        if key not in plan:
            raise ValueError(f"Missing required key in fill_plan.json: {key}")

    if not os.path.exists(plan["template_file"]):
        raise FileNotFoundError(f"Template file not found: {plan['template_file']}")

    return plan


def find_section_xmls(hwpx_path: str) -> list[str]:
    """Find all section XML files in HWPX archive."""
    sections = []
    with zipfile.ZipFile(hwpx_path, "r") as zf:
        for name in zf.namelist():
            if name.startswith("Contents/section") and name.endswith(".xml"):
                sections.append(name)
    sections.sort()
    return sections


def get_all_text_elements(tree) -> list:
    """Get all <hp:t> text elements from an XML tree."""
    return tree.findall(f".//{HP_T_TAG}")


def apply_simple_replacements_xml(tree, replacements: list) -> int:
    """Apply exact text match replacements on XML tree.

    Each replacement: {"find": str, "replace": str, "occurrence"?: int}
    Replacements are sorted by find text length (longest first) to prevent
    shorter matches from breaking longer ones.
    """
    total = 0
    text_elements = get_all_text_elements(tree)

    # Sort by find text length descending to avoid partial match conflicts
    sorted_replacements = sorted(replacements, key=lambda r: len(r["find"]), reverse=True)

    for r in sorted_replacements:
        find_text = r["find"]
        replace_text = r["replace"]
        limit = r.get("occurrence")
        count = 0

        for elem_idx, elem in enumerate(text_elements):
            if elem.text and find_text in elem.text:
                elem.text = elem.text.replace(find_text, replace_text, 1)
                count += 1
                _log_event({"type": "replace", "idx": elem_idx, "find": find_text, "replace": replace_text})
                if limit and count >= limit:
                    break

        total += count
        find_display = find_text[:50] + ("..." if len(find_text) > 50 else "")
        replace_display = replace_text[:50] + ("..." if len(replace_text) > 50 else "")
        if count == 0:
            print(f"  WARNING: '{find_display}' not found", file=sys.stderr)
        else:
            print(f"  Replaced '{find_display}' -> '{replace_display}' ({count}x)")

    return total


def apply_section_replacements_xml(tree, replacements: list) -> int:
    """Replace guide text with actual content on XML tree.

    Each replacement: {"section_id": str, "guide_text_prefix": str, "content": str}
    """
    parent_map = _build_parent_map(tree)
    text_elements = get_all_text_elements(tree)
    total = 0

    for r in replacements:
        prefix = r["guide_text_prefix"]
        content = r["content"]
        section_id = r.get("section_id", "?")
        clear_cell = r.get("clear_cell", True)
        replaced = False

        for elem_idx, elem in enumerate(text_elements):
            if elem.text and prefix in elem.text:
                elem.text = content
                for child in list(elem):
                    elem.remove(child)

                if clear_cell:
                    cell = _get_ancestor(elem, "tc", parent_map)
                    if cell is not None:
                        _clear_cell_except(cell, elem, parent_map)

                total += 1
                replaced = True
                _log_event({"type": "replace", "idx": elem_idx, "find": prefix, "replace": content})
                if clear_cell:
                    print(f"  Section {section_id}: replaced guide text (cell cleared)")
                else:
                    print(f"  Section {section_id}: replaced guide text")
                break

        if not replaced:
            prefix_display = prefix[:50] + ("..." if len(prefix) > 50 else "")
            print(
                f"  WARNING: Section {section_id} guide text not found: '{prefix_display}'",
                file=sys.stderr,
            )

    return total


def apply_table_cell_fills_xml(tree, fills: list) -> int:
    """Fill table cells by finding label text and replacing the adjacent value cell.

    Each fill: {"find_label": str, "value": str}

    Strategy: Find <hp:t> with the label text, then find the next <hp:t> element
    that is in a different table cell (different parent chain) and replace it.
    """
    total = 0
    text_elements = get_all_text_elements(tree)

    # Build parent map for cell boundary detection
    parent_map = {}
    for parent in tree.iter():
        for child in parent:
            parent_map[child] = parent

    def get_cell_ancestor(elem):
        """Walk up to find the nearest table cell (hp:tc or similar)."""
        current = elem
        while current is not None:
            tag = current.tag if isinstance(current.tag, str) else ""
            if "tc" in tag.lower() or "cell" in tag.lower():
                return current
            current = parent_map.get(current)
        return None

    for fill in fills:
        label = fill["find_label"]
        value = fill["value"]
        found = False

        for i, elem in enumerate(text_elements):
            if elem.text and label in elem.text:
                label_cell = get_cell_ancestor(elem)

                # Look for next non-empty text in a DIFFERENT cell
                for j in range(i + 1, min(i + 30, len(text_elements))):
                    next_elem = text_elements[j]
                    if next_elem.text and next_elem.text.strip():
                        next_cell = get_cell_ancestor(next_elem)
                        # Only replace if it's in a different cell (or no cell found)
                        if next_cell is not label_cell or next_cell is None:
                            next_elem.text = value
                            total += 1
                            found = True
                            _log_event({"type": "replace", "idx": j, "find": label, "replace": value})
                            value_display = value[:40] + ("..." if len(value) > 40 else "")
                            print(f"  Table cell '{label}' -> '{value_display}'")
                            break
                break

        if not found:
            print(f"  WARNING: Table label '{label}' not found or no adjacent cell", file=sys.stderr)

    return total


def fill_hwpx(plan: dict, output_path: str) -> int:
    """Main fill operation: copy template, modify XML, save."""
    template_path = plan["template_file"]

    # Copy template to output
    shutil.copy2(template_path, output_path)

    # Find section XMLs
    section_files = find_section_xmls(template_path)
    if not section_files:
        raise ValueError("No section XML files found in HWPX")

    print(f"Found {len(section_files)} section(s): {', '.join(section_files)}")

    total_replacements = 0

    # Process each section XML
    with zipfile.ZipFile(template_path, "r") as zf_in:
        for section_file in section_files:
            xml_bytes = zf_in.read(section_file)
            tree = etree.fromstring(xml_bytes)

            section_total = 0

            # 1. Simple replacements
            if plan.get("simple_replacements"):
                print(f"\n--- Simple Replacements ({section_file}) ---")
                section_total += apply_simple_replacements_xml(tree, plan["simple_replacements"])

            # 2. Section replacements
            if plan.get("section_replacements"):
                print(f"\n--- Section Replacements ({section_file}) ---")
                section_total += apply_section_replacements_xml(tree, plan["section_replacements"])

            # 3. Table cell fills
            if plan.get("table_cell_fills"):
                print(f"\n--- Table Cell Fills ({section_file}) ---")
                section_total += apply_table_cell_fills_xml(tree, plan["table_cell_fills"])

            total_replacements += section_total

            if section_total > 0:
                # Write modified XML back into the ZIP
                modified_xml = etree.tostring(tree, xml_declaration=True, encoding="UTF-8")
                _update_zip_file(output_path, section_file, modified_xml)
                print(f"  Updated {section_file} ({section_total} replacements)")

    _log_event({"type": "done", "total": total_replacements, "output": output_path})
    return total_replacements


def _update_zip_file(zip_path: str, target_file: str, new_content: bytes) -> None:
    """Replace a single file inside a ZIP archive."""
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".hwpx")
    os.close(tmp_fd)

    with zipfile.ZipFile(zip_path, "r") as zf_in, \
         zipfile.ZipFile(tmp_path, "w") as zf_out:
        for item in zf_in.infolist():
            if item.filename == target_file:
                zf_out.writestr(item, new_content)
            else:
                zf_out.writestr(item, zf_in.read(item.filename))

    shutil.move(tmp_path, zip_path)


def inspect_template(template_path: str, query: str | None = None) -> None:
    """List all <hp:t> text elements in a template for debugging.

    Uses direct XML parsing to find ALL text including table cells.
    """
    section_files = find_section_xmls(template_path)

    total_elements = 0
    with zipfile.ZipFile(template_path, "r") as zf:
        for section_file in section_files:
            xml_bytes = zf.read(section_file)
            tree = etree.fromstring(xml_bytes)
            text_elements = get_all_text_elements(tree)
            total_elements += len(text_elements)

            print(f"Section: {section_file} ({len(text_elements)} text elements)\n")

            for i, elem in enumerate(text_elements):
                text = elem.text or ""
                if not text.strip():
                    continue
                if query and query.lower() not in text.lower():
                    continue
                display = text[:100] + ("..." if len(text) > 100 else "")
                print(f"  [{i:4d}] {display}")

    print(f"\nTotal <hp:t> elements: {total_elements}")


def main():
    parser = argparse.ArgumentParser(description="Fill HWPX template with content")
    parser.add_argument("plan", nargs="?", help="Path to fill_plan.json")
    parser.add_argument("-o", "--output", help="Override output path")
    parser.add_argument("--inspect", metavar="HWPX", help="Inspect template text runs")
    parser.add_argument("-q", "--query", help="Filter runs by text (with --inspect)")
    args = parser.parse_args()

    if args.inspect:
        inspect_template(args.inspect, args.query)
        return

    if not args.plan:
        parser.error("fill_plan.json is required (or use --inspect)")

    # Load plan
    plan = load_plan(args.plan)
    template_path = plan["template_file"]
    output_path = args.output or plan["output_file"]

    print(f"Template: {template_path}")
    print(f"Output:   {output_path}")
    print()

    # Fill template
    total = fill_hwpx(plan, output_path)

    # Report
    size = os.path.getsize(output_path)
    print(f"\n--- Done ---")
    print(f"Saved: {output_path} ({size:,} bytes)")
    print(f"Total replacements: {total}")


if __name__ == "__main__":
    main()
