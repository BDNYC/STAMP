#!/usr/bin/env python3

from astropy.io import fits

# Replace these with your exact paths
files = [
    "/Users/anthonymunozperez/Desktop/brightness_map_for_stuff/NIRSpec_1/W1049A_NIRSpec_fluxarr_originalcadence.fits",
    "/Users/anthonymunozperez/Desktop/brightness_map_for_stuff/NIRSpec_1/W1049A_NIRSpec_fluxarr.fits"
]

for path in files:
    print("="*80)
    print(f"Inspecting file: {path}")
    print("-"*80)
    try:
        with fits.open(path) as hdul:
            # Summary of all HDUs
            hdul.info()

            # Detailed inspection
            for i, hdu in enumerate(hdul):
                print(f"\nHDU {i}:")
                print(f"  Name       : {hdu.name}")
                print(f"  Header keys: {list(hdu.header.keys())[:10]}{'...' if len(hdu.header)>10 else ''}")
                if hdu.data is not None:
                    data = hdu.data
                    print(f"  Data shape : {data.shape}")
                    flat = data.flatten()
                    # show up to first 5 values
                    sample = flat[:5] if flat.size>=5 else flat
                    print(f"  Sample vals: {sample}")
                else:
                    print("  No data in this HDU")
    except Exception as e:
        print(f"Error opening {path}: {e}")
    print("\n")

