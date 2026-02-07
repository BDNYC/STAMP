"""
Disk-based cache for processed JWST datasets.
Stores FITS parsing results to speed up repeated processing.
"""

import os
import hashlib
import pickle
import json
import time
import tempfile
import numpy as np
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class DatasetCache:
    """LRU disk cache with TTL expiration and size limits."""

    def __init__(self, cache_dir=None, ttl_hours=24, max_cache_size_gb=10):
        self.cache_dir = cache_dir or os.path.join(
            tempfile.gettempdir(),
            'jwst_stamp_cache'
        )
        self.ttl_seconds = ttl_hours * 3600
        self.max_cache_bytes = max_cache_size_gb * 1024 * 1024 * 1024

        os.makedirs(self.cache_dir, exist_ok=True)
        logger.info(f"Cache initialized: {self.cache_dir} "
                    f"(TTL: {ttl_hours}h, Max size: {max_cache_size_gb}GB)")

    def _compute_hash(self, file_path, use_interpolation, num_integrations=None):
        """Compute a unique hash based on file content and parameters."""
        hasher = hashlib.sha256()

        try:
            file_size = 0
            with open(file_path, 'rb') as f:
                while chunk := f.read(8192):
                    hasher.update(chunk)
                    file_size += len(chunk)
            logger.info(f"Hashing file: {os.path.basename(file_path)} (size: {file_size / 1024 / 1024:.2f} MB)")
        except Exception as e:
            logger.error(f"Error hashing file {file_path}: {e}")
            raise

        hasher.update(str(use_interpolation).encode())

        cache_key = hasher.hexdigest()

        logger.info(f"Cache key: {cache_key[:16]}... | File: {os.path.basename(file_path)} | "
                    f"Interpolation: {use_interpolation}")

        return cache_key

    def _get_cache_path(self, cache_key):
        return os.path.join(self.cache_dir, f"{cache_key}.pkl")

    def _get_metadata_path(self, cache_key):
        return os.path.join(self.cache_dir, f"{cache_key}_meta.json")

    def get(self, file_path, use_interpolation, num_integrations=None):
        """Retrieve cached data if available and valid. Returns dict or None."""
        try:
            cache_key = self._compute_hash(file_path, use_interpolation, num_integrations)
            cache_path = self._get_cache_path(cache_key)
            meta_path = self._get_metadata_path(cache_key)

            if not os.path.exists(cache_path) or not os.path.exists(meta_path):
                logger.info(f"Cache miss: key {cache_key[:12]}...not found")
                return None

            with open(meta_path, 'r') as f:
                metadata = json.load(f)

            age = time.time() - metadata['timestamp']
            if age > self.ttl_seconds:
                logger.info(f"Cache expired: key {cache_key[:12]}..."
                            f"(age: {age / 3600:.1f}h > {self.ttl_seconds / 3600:.1f}h)")
                self._remove_entry(cache_key)
                return None

            logger.info(f"Cache HIT: key {cache_key[:12]}..."
                        f"(age: {age / 60:.1f}m, size: {metadata['size'] / 1024 / 1024:.1f}MB)")

            with open(cache_path, 'rb') as f:
                data = pickle.load(f)

            metadata['last_access'] = time.time()
            metadata['access_count'] = metadata.get('access_count', 0) + 1
            with open(meta_path, 'w') as f:
                json.dump(metadata, f, indent=2)

            return data

        except Exception as e:
            logger.error(f"Error reading cache: {e}", exc_info=True)
            return None

    def set(self, file_path, use_interpolation, data, num_integrations=None):
        """Store processed data in cache."""
        try:
            cache_key = self._compute_hash(file_path, use_interpolation, num_integrations)
            cache_path = self._get_cache_path(cache_key)
            meta_path = self._get_metadata_path(cache_key)

            logger.info(f"Caching data for key {cache_key[:12]}...")
            with open(cache_path, 'wb') as f:
                pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)

            file_size = os.path.getsize(cache_path)
            metadata = {
                'timestamp': time.time(),
                'last_access': time.time(),
                'access_count': 0,
                'cache_key': cache_key,
                'size': file_size,
                'original_file': os.path.basename(file_path),
                'use_interpolation': use_interpolation,
                'data_info': {
                    'wavelength_points': len(data.get('wavelength_1d', [])),
                    'time_points': len(data.get('time_1d', [])),
                    'total_integrations': data.get('metadata', {}).get('total_integrations', 'unknown')
                }
            }

            with open(meta_path, 'w') as f:
                json.dump(metadata, f, indent=2)

            logger.info(f"Cached successfully: {file_size / 1024 / 1024:.1f} MB "
                        f"({metadata['data_info']['wavelength_points']} wavelengths, "
                        f"{metadata['data_info']['time_points']} time points)")

            self._enforce_size_limit()

        except Exception as e:
            logger.error(f"Error writing cache: {e}", exc_info=True)

    def _remove_entry(self, cache_key):
        """Remove a cache entry (data + metadata files)."""
        try:
            cache_path = self._get_cache_path(cache_key)
            meta_path = self._get_metadata_path(cache_key)

            if os.path.exists(cache_path):
                os.remove(cache_path)
                logger.debug(f"Removed cache data: {cache_key[:12]}...")

            if os.path.exists(meta_path):
                os.remove(meta_path)
                logger.debug(f"Removed cache metadata: {cache_key[:12]}...")

        except Exception as e:
            logger.error(f"Error removing cache entry {cache_key[:12]}...: {e}")

    def _enforce_size_limit(self):
        """Remove oldest entries if total size exceeds limit (LRU eviction)."""
        try:
            entries = []
            for fname in os.listdir(self.cache_dir):
                if fname.endswith('_meta.json'):
                    meta_path = os.path.join(self.cache_dir, fname)
                    try:
                        with open(meta_path, 'r') as f:
                            metadata = json.load(f)
                        entries.append(metadata)
                    except Exception as e:
                        logger.warning(f"Could not read metadata {fname}: {e}")
                        continue

            total_size = sum(e['size'] for e in entries)

            if total_size > self.max_cache_bytes:
                logger.warning(
                    f"Cache size {total_size / 1024 / 1024 / 1024:.2f} GB exceeds "
                    f"limit of {self.max_cache_bytes / 1024 / 1024 / 1024:.2f} GB."
                    f"Removing oldest entries..."
                )

                entries.sort(key=lambda e: e.get('last_access', 0))
                target_size = self.max_cache_bytes * 0.8
                removed_count = 0

                for entry in entries:
                    if total_size <= target_size:
                        break
                    self._remove_entry(entry['cache_key'])
                    total_size -= entry['size']
                    removed_count += 1

                logger.info(
                    f"Cache cleanup complete: removed {removed_count} entries, "
                    f"new size: {total_size / 1024 / 1024 / 1024:.2f} GB"
                )

        except Exception as e:
            logger.error(f"Error enforcing cache size limit: {e}", exc_info=True)

    def clear(self):
        """Clear all cache entries."""
        try:
            removed_count = 0
            for fname in os.listdir(self.cache_dir):
                fpath = os.path.join(self.cache_dir, fname)
                if os.path.isfile(fpath):
                    os.remove(fpath)
                    removed_count += 1

            logger.info(f"Cache cleared: {removed_count} files removed")
            return removed_count

        except Exception as e:
            logger.error(f"Error clearing cache: {e}", exc_info=True)
            return 0

    def get_stats(self):
        """Get cache statistics."""
        try:
            entries = []
            for fname in os.listdir(self.cache_dir):
                if fname.endswith('_meta.json'):
                    meta_path = os.path.join(self.cache_dir, fname)
                    try:
                        with open(meta_path, 'r') as f:
                            metadata = json.load(f)
                        entries.append(metadata)
                    except Exception:
                        continue

            total_size = sum(e['size'] for e in entries)

            return {
                'num_entries': len(entries),
                'total_size_mb': total_size / 1024 / 1024,
                'total_size_gb': total_size / 1024 / 1024 / 1024,
                'max_size_gb': self.max_cache_bytes / 1024 / 1024 / 1024,
                'ttl_hours': self.ttl_seconds / 3600,
                'cache_dir': self.cache_dir,
                'entries': sorted(entries,
                                  key=lambda e: e.get('last_access', 0),
                                  reverse=True)
            }

        except Exception as e:
            logger.error(f"Error getting cache stats: {e}", exc_info=True)
            return {
                'num_entries': 0,
                'total_size_mb': 0,
                'total_size_gb': 0,
                'error': str(e)
            }
