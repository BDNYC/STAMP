#!/usr/bin/env python3
"""Master orchestrator: download all atmospheric model grids for SA3D.

Runs individual grid download scripts in recommended order (smallest first),
with cleanup between batches to stay within disk limits.

Batch order:
    1. ATMO 2020 (all 3 sub-grids)      ~50 MB
    2. DRIFT-PHOENIX                      ~50 MB
    3. Morley 2012                        ~100 MB
    4. BT-Settl CIFIST                    ~2.5 GB
    5. Exo-REM Low-Res                    ~700 MB
    6. Sonora Bobcat                      ~3 GB
    7. Sonora Elf Owl Y                   ~20 GB peak
    8. Sonora Elf Owl T                   ~20 GB peak
    9. Sonora Elf Owl L                   ~20 GB peak

Usage:
    python scripts/download_all_grids.py [options]

Options:
    --start-batch N    Start from batch N (default: 1)
    --pause            Pause between batches for confirmation
    --skip GRID        Skip specific grid(s) (comma-separated)
    --dry-run          Show what would be run without executing
"""

import os
import sys
import subprocess
import argparse
import time


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

BATCHES = [
    {
        "batch": 1,
        "name": "ATMO 2020 (CEQ)",
        "script": "download_atmo2020.py",
        "args": ["--subgrid", "ceq"],
        "skip_key": "atmo2020_ceq",
        "peak_disk": "~20 MB",
    },
    {
        "batch": 1,
        "name": "ATMO 2020 (NEQ Strong)",
        "script": "download_atmo2020.py",
        "args": ["--subgrid", "neq_strong"],
        "skip_key": "atmo2020_neq_strong",
        "peak_disk": "~15 MB",
    },
    {
        "batch": 1,
        "name": "ATMO 2020 (NEQ Weak)",
        "script": "download_atmo2020.py",
        "args": ["--subgrid", "neq_weak"],
        "skip_key": "atmo2020_neq_weak",
        "peak_disk": "~15 MB",
    },
    {
        "batch": 2,
        "name": "DRIFT-PHOENIX",
        "script": "download_drift_phoenix.py",
        "args": [],
        "skip_key": "drift_phoenix",
        "peak_disk": "~50 MB",
    },
    {
        "batch": 3,
        "name": "Morley 2012 (Sulfide Clouds)",
        "script": "download_morley2012.py",
        "args": [],
        "skip_key": "morley2012",
        "peak_disk": "~100 MB",
    },
    {
        "batch": 4,
        "name": "BT-Settl CIFIST",
        "script": "download_btsettl.py",
        "args": [],
        "skip_key": "bt_settl",
        "peak_disk": "~2.5 GB",
    },
    {
        "batch": 5,
        "name": "Exo-REM Low-Res (Cloudless)",
        "script": "download_exorem.py",
        "args": [],
        "skip_key": "exorem",
        "peak_disk": "~700 MB",
    },
    {
        "batch": 6,
        "name": "Sonora Bobcat",
        "script": "download_sonora_bobcat.py",
        "args": [],
        "skip_key": "sonora_bobcat",
        "peak_disk": "~3 GB",
    },
    {
        "batch": 7,
        "name": "Sonora Elf Owl Y",
        "script": "download_sonora_elfowl.py",
        "args": ["--subgrid", "Y"],
        "skip_key": "elfowl_Y",
        "peak_disk": "~20 GB",
    },
    {
        "batch": 8,
        "name": "Sonora Elf Owl T",
        "script": "download_sonora_elfowl.py",
        "args": ["--subgrid", "T"],
        "skip_key": "elfowl_T",
        "peak_disk": "~20 GB",
    },
    {
        "batch": 9,
        "name": "Sonora Elf Owl L",
        "script": "download_sonora_elfowl.py",
        "args": ["--subgrid", "L"],
        "skip_key": "elfowl_L",
        "peak_disk": "~20 GB",
    },
]


def main():
    parser = argparse.ArgumentParser(
        description="Download all atmospheric model grids for SA3D"
    )
    parser.add_argument(
        "--start-batch", type=int, default=1,
        help="Start from batch N (default: 1)"
    )
    parser.add_argument(
        "--pause", action="store_true",
        help="Pause between batches for user confirmation"
    )
    parser.add_argument(
        "--skip", type=str, default="",
        help="Comma-separated grid skip keys (e.g. 'bt_settl,elfowl_Y')"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be run without executing"
    )
    parser.add_argument(
        "--forward-args", type=str, default="",
        help="Extra arguments forwarded to all scripts (e.g. '--keep-raw')"
    )
    args = parser.parse_args()

    skip_keys = set(s.strip() for s in args.skip.split(",") if s.strip())
    forward = args.forward_args.split() if args.forward_args else []

    print("=" * 60)
    print("  SA3D Model Grid Downloader — Master Orchestrator")
    print("=" * 60)
    print(f"  Start batch:  {args.start_batch}")
    print(f"  Skip:         {skip_keys or 'none'}")
    print(f"  Pause:        {args.pause}")
    print(f"  Dry run:      {args.dry_run}")
    if forward:
        print(f"  Forward args: {forward}")
    print()

    # Filter and group batches
    tasks = [
        b for b in BATCHES
        if b["batch"] >= args.start_batch and b["skip_key"] not in skip_keys
    ]

    if not tasks:
        print("Nothing to do (all batches skipped or start-batch too high).")
        return

    # Show plan
    print("Execution plan:")
    current_batch = None
    for t in tasks:
        if t["batch"] != current_batch:
            current_batch = t["batch"]
            print(f"\n  Batch {current_batch}:")
        print(f"    {t['name']}  (peak: {t['peak_disk']})")

    print(f"\n  Total: {len(tasks)} grid downloads")

    if args.dry_run:
        print("\n--- Dry run: commands that would be executed ---\n")
        for t in tasks:
            script_path = os.path.join(SCRIPT_DIR, t["script"])
            cmd = [sys.executable, script_path] + t["args"] + forward
            print(f"  {' '.join(cmd)}")
        print("\nDry run complete. Nothing was downloaded.")
        return

    # Execute
    completed = 0
    failed = []
    current_batch = None

    for t in tasks:
        # Batch transition
        if t["batch"] != current_batch:
            if current_batch is not None and args.pause:
                print(f"\n--- Batch {current_batch} complete ---")
                try:
                    input("Press Enter to continue to next batch "
                          "(Ctrl+C to abort)... ")
                except KeyboardInterrupt:
                    print("\nAborted by user.")
                    break
            current_batch = t["batch"]
            print(f"\n{'=' * 60}")
            print(f"  Batch {current_batch}")
            print(f"{'=' * 60}")

        script_path = os.path.join(SCRIPT_DIR, t["script"])
        cmd = [sys.executable, script_path] + t["args"] + forward

        print(f"\n>>> {t['name']} (peak: {t['peak_disk']})")
        print(f"    Command: {' '.join(cmd)}\n")

        start_time = time.time()
        result = subprocess.run(cmd, cwd=os.path.dirname(SCRIPT_DIR))
        elapsed = time.time() - start_time

        if result.returncode == 0:
            completed += 1
            print(f"\n<<< {t['name']} completed in {elapsed:.0f}s")
        else:
            failed.append(t["name"])
            print(f"\n<<< {t['name']} FAILED (exit code {result.returncode}, "
                  f"{elapsed:.0f}s)")

    # Final summary
    print(f"\n{'=' * 60}")
    print(f"  All batches complete")
    print(f"  Completed: {completed}/{len(tasks)}")
    if failed:
        print(f"  Failed:    {len(failed)}")
        for name in failed:
            print(f"    - {name}")
    print(f"{'=' * 60}")

    if failed:
        print("\nTo retry failed grids, run them individually.")
        sys.exit(1)


if __name__ == "__main__":
    main()
