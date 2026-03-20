#!/usr/bin/env python3
"""
susfs_manual_fix.py
Manual patch applicator untuk known rejects SUSFS di kernel sweet (sm6150/SDM732).
"""

import sys, os, re

# ── Fix A: kernel/sys.c ──────────────────────────────────────────────────────
print("Fixing kernel/sys.c ...")
with open("kernel/sys.c", "r") as f:
    data = f.read()

if "susfs_spoof_uname" not in data:
    anchor = "\tdown_read(&uts_sem);\n\tmemcpy(&tmp, utsname(), sizeof(tmp));\n\tup_read(&uts_sem);"
    replacement = (
        "\tdown_read(&uts_sem);\n"
        "\tmemcpy(&tmp, utsname(), sizeof(tmp));\n"
        "#ifdef CONFIG_KSU_SUSFS_SPOOF_UNAME\n"
        "\tsusfs_spoof_uname(&tmp);\n"
        "#endif\n"
        "\tup_read(&uts_sem);"
    )
    extern_anchor = "SYSCALL_DEFINE1(newuname,"
    extern_inject = (
        "#ifdef CONFIG_KSU_SUSFS_SPOOF_UNAME\n"
        "extern void susfs_spoof_uname(struct new_utsname* tmp);\n"
        "#endif\n"
        "SYSCALL_DEFINE1(newuname,"
    )
    if anchor in data:
        data = data.replace(extern_anchor, extern_inject, 1)
        data = data.replace(anchor, replacement, 1)
        with open("kernel/sys.c", "w") as f:
            f.write(data)
        print("  OK  kernel/sys.c patched")
    else:
        print("  WARN kernel/sys.c anchor not found — skipping")
else:
    print("  OK  kernel/sys.c already patched")

# ── Fix B: fs/proc/task_mmu.c — bypass_orig_flow label ──────────────────────
# Problem: patch inject `goto bypass_orig_flow` berhasil (hunk #4),
# tapi hunk #5 yang inject label `bypass_orig_flow:` gagal apply.
# Akibatnya label masuk di tempat yang salah (fungsi berbeda) atau tidak masuk sama sekali.
#
# Fix: hapus label yang salah posisi (jika ada), lalu inject ulang di tempat yang
# benar — yaitu tepat setelah closing brace dari blok yang berisi goto.
#
# Struktur di task_mmu.c setelah patch (dari SUSFS pattern 4.14):
#   show_map_vma(struct seq_file *m, struct vm_area_struct *vma, ...) {
#     ...
#     if (susfs_show_map_vma_spoofer(m, vma))
#         goto bypass_orig_flow;       <- line ~1046
#     ... [existing show_map_vma body] ...
#     bypass_orig_flow:                <- label harus di sini, sebelum closing }
#   }
#
print("Fixing fs/proc/task_mmu.c ...")
with open("fs/proc/task_mmu.c", "r") as f:
    content = f.read()

goto_present   = "goto bypass_orig_flow;" in content
label_present  = "bypass_orig_flow:" in content

if not goto_present:
    print("  OK  fs/proc/task_mmu.c no goto present, nothing to fix")
elif goto_present and label_present:
    # Label ada — tapi mungkin di fungsi yang salah. Cek apakah goto dan label
    # ada di dalam fungsi yang SAMA dengan cara mencari function boundary.
    lines = content.split("\n")
    goto_line  = next(i for i, l in enumerate(lines) if "goto bypass_orig_flow;" in l)
    label_line = next(i for i, l in enumerate(lines) if "bypass_orig_flow:" in l and "goto" not in l)

    # Temukan fungsi yang mengandung goto_line
    # Cari opening brace fungsi ke atas dari goto_line
    func_start = None
    brace_depth = 0
    for i in range(goto_line, -1, -1):
        brace_depth += lines[i].count('}') - lines[i].count('{')
        if brace_depth > 0:
            func_start = i
            break

    # Temukan closing brace fungsi (func_end) dari goto_line ke bawah
    brace_depth = 0
    func_end = None
    for i in range(goto_line, len(lines)):
        brace_depth += lines[i].count('{') - lines[i].count('}')
        if brace_depth < 0:
            func_end = i
            break

    if func_start is not None and func_end is not None and not (func_start <= label_line <= func_end):
        print(f"  WARN label at line {label_line+1} is OUTSIDE function scope ({func_start+1}..{func_end+1})")
        print(f"  Removing misplaced label and re-injecting...")

        # Hapus baris label yang salah
        lines = [l for i, l in enumerate(lines) if not (i == label_line and "bypass_orig_flow:" in l and "goto" not in l)]

        # Inject label tepat sebelum closing brace fungsi (func_end - 1 setelah delete)
        # Recalculate func_end setelah delete
        content_tmp = "\n".join(lines)
        lines = content_tmp.split("\n")

        goto_line2 = next(i for i, l in enumerate(lines) if "goto bypass_orig_flow;" in l)
        brace_depth = 0
        func_end2 = None
        for i in range(goto_line2, len(lines)):
            brace_depth += lines[i].count('{') - lines[i].count('}')
            if brace_depth < 0:
                func_end2 = i
                break

        if func_end2 is not None:
            lines.insert(func_end2, "bypass_orig_flow:")
            content = "\n".join(lines)
            with open("fs/proc/task_mmu.c", "w") as f:
                f.write(content)
            print(f"  OK  fs/proc/task_mmu.c label re-injected before line {func_end2+1}")
        else:
            print("  ERR could not find function end")
            sys.exit(1)
    else:
        print(f"  OK  fs/proc/task_mmu.c goto (line {goto_line+1}) and label (line {label_line+1}) in same function")

elif goto_present and not label_present:
    # Label belum ada sama sekali — inject sebelum closing brace fungsi yang punya goto
    print("  Label missing entirely, injecting...")
    lines = content.split("\n")
    goto_line = next(i for i, l in enumerate(lines) if "goto bypass_orig_flow;" in l)
    brace_depth = 0
    func_end = None
    for i in range(goto_line, len(lines)):
        brace_depth += lines[i].count('{') - lines[i].count('}')
        if brace_depth < 0:
            func_end = i
            break
    if func_end is not None:
        lines.insert(func_end, "bypass_orig_flow:")
        content = "\n".join(lines)
        with open("fs/proc/task_mmu.c", "w") as f:
            f.write(content)
        print(f"  OK  fs/proc/task_mmu.c label injected before closing brace at line {func_end+1}")
    else:
        print("  ERR cannot find function end")
        sys.exit(1)

# ── Fix C: scan semua .c yang punya susfs calls tapi belum include susfs.h ───
print("\nScanning for missing susfs.h includes ...")

INCLUDE_ANCHORS = [
    "#include <linux/fs.h>",
    "#include <linux/file.h>",
    "#include <linux/fdtable.h>",
    "#include <linux/namei.h>",
    "#include <linux/kernel.h>",
    "#include <linux/slab.h>",
    "#include <linux/mm.h>",
]

def inject_susfs_include(fpath):
    with open(fpath, "r", errors="replace") as f:
        content = f.read()
    if "#include <linux/susfs.h>" in content:
        return "already"
    for anchor in INCLUDE_ANCHORS:
        if anchor in content:
            content = content.replace(anchor, anchor + "\n#include <linux/susfs.h>", 1)
            with open(fpath, "w") as f:
                f.write(content)
            return f"injected after '{anchor}'"
    lines = content.split("\n")
    last_inc = max((i for i, l in enumerate(lines) if l.startswith("#include ")), default=None)
    if last_inc is not None:
        lines.insert(last_inc + 1, "#include <linux/susfs.h>")
        with open(fpath, "w") as f:
            f.write("\n".join(lines))
        return "injected (fallback after last include)"
    return "FAILED no anchor found"

found = False
for root, dirs, files in os.walk("."):
    dirs[:] = [d for d in dirs if d not in ("susfs4ksu", "out", ".git")]
    for fname in files:
        if not fname.endswith(".c"):
            continue
        fpath = os.path.join(root, fname)
        try:
            with open(fpath, "r", errors="replace") as f:
                fc = f.read()
        except Exception:
            continue
        if "#include <linux/susfs.h>" in fc:
            continue
        calls = re.findall(r'\bsusfs_\w+\s*\(', fc)
        if not calls:
            continue
        found = True
        result = inject_susfs_include(fpath)
        if "FAILED" in result:
            print(f"  ERR {fpath}: {result}")
            sys.exit(1)
        else:
            print(f"  OK  {fpath}: {result} (calls: {calls[:3]})")

if not found:
    print("  OK  No files need susfs.h injection")

print("\nManual fixes done.")
