#!/usr/bin/env python3
"""
susfs_manual_fix.py
Manual patch applicator untuk known rejects SUSFS di kernel sweet (sm6150/SDM732).

Dijalankan setelah `patch --batch --forward` di step SUSFS_INTEGRATION.
Dua fix:
  A) kernel/sys.c  — inject susfs_spoof_uname() call ke SYSCALL_DEFINE1(newuname)
  B) fs/open.c     — pastikan #include <linux/susfs.h> ada kalau susfs call sudah masuk
"""

import sys

# ── Fix A: kernel/sys.c ──────────────────────────────────────────────────────
print("Fixing kernel/sys.c ...")
with open("kernel/sys.c", "r") as f:
    data = f.read()

if "susfs_spoof_uname" not in data:
    # Anchor: blok down_read/memcpy/up_read di dalam newuname syscall
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
        print("  WARN kernel/sys.c anchor not found — may already be patched differently, skipping")
else:
    print("  OK  kernel/sys.c already patched, skipping")

# ── Fix B: fs/open.c ─────────────────────────────────────────────────────────
print("Fixing fs/open.c ...")
with open("fs/open.c", "r") as f:
    data = f.read()

if "susfs_is_current_proc_umounted" in data and "#include <linux/susfs.h>" not in data:
    data = data.replace(
        "#include <linux/fs.h>",
        "#include <linux/fs.h>\n#include <linux/susfs.h>",
        1
    )
    with open("fs/open.c", "w") as f:
        f.write(data)
    print("  OK  fs/open.c susfs.h include added")
elif "susfs_is_current_proc_umounted" not in data:
    print("  WARN fs/open.c susfs call not found — SUSFS patch may not have applied to this file")
    sys.exit(1)
else:
    print("  OK  fs/open.c already OK")

print("Manual fixes done.")
