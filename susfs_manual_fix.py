#!/usr/bin/env python3
"""
susfs_manual_fix.py
Manual patch applicator untuk known rejects SUSFS di kernel sweet (sm6150/SDM732).

Fix:
  A) kernel/sys.c  — inject susfs_spoof_uname() ke SYSCALL_DEFINE1(newuname)
  B) fs/open.c     — inject #include <linux/susfs.h> supaya susfs calls bisa resolve
  C) Verify pass   — scan semua .c file yang punya susfs calls tapi belum include susfs.h
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

# ── Fix B+C: scan semua .c yang punya susfs calls tapi belum include susfs.h ─
# Ini cover fs/open.c dan file lain yang mungkin diinject oleh susfs_inline_hook_patches.sh
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
    # Cari anchor terbaik
    for anchor in INCLUDE_ANCHORS:
        if anchor in content:
            content = content.replace(anchor, anchor + "\n#include <linux/susfs.h>", 1)
            with open(fpath, "w") as f:
                f.write(content)
            return f"injected after '{anchor}'"
    # Fallback: setelah include terakhir
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
                content = f.read()
        except Exception:
            continue
        if "#include <linux/susfs.h>" in content:
            continue
        calls = re.findall(r'\bsusfs_\w+\s*\(', content)
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
