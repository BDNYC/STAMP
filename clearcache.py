#!/usr/bin/env python3
"""
Clear JWST STAMP cache

This script clears the cache used by the STAMP application.
Run this if you're experiencing issues with cached data.
"""

import os
import shutil
import tempfile
from pathlib import Path


def clear_cache():
    """Clear the JWST STAMP cache directory."""

    # Default cache location (same as in cache_manager.py)
    cache_dir = os.path.join(tempfile.gettempdir(), 'jwst_stamp_cache')

    print("=" * 60)
    print("JWST STAMP Cache Cleaner")
    print("=" * 60)
    print(f"\nCache directory: {cache_dir}")

    if not os.path.exists(cache_dir):
        print("\nCache directory doesn't exist - nothing to clear!")
        return

    # Count files before deletion
    file_count = 0
    total_size = 0

    try:
        for root, dirs, files in os.walk(cache_dir):
            for file in files:
                file_path = os.path.join(root, file)
                try:
                    file_size = os.path.getsize(file_path)
                    total_size += file_size
                    file_count += 1
                except Exception:
                    pass

        print(f"\nFound {file_count} cache files")
        print(f"Total size: {total_size / 1024 / 1024:.2f} MB")

        # Confirm deletion
        response = input("\nDelete all cache files? (yes/no): ").strip().lower()

        if response in ['yes', 'y']:
            shutil.rmtree(cache_dir)
            print(f"\nCache cleared successfully!")
            print(f"   Deleted {file_count} files ({total_size / 1024 / 1024:.2f} MB)")
        else:
            print("\nCache clearing cancelled")

    except Exception as e:
        print(f"\nError clearing cache:  {e}")
        return


if __name__ == '__main__':
    clear_cache()