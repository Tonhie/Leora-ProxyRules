#!/usr/bin/env python3
"""Download pinned official Linux CI cores and verify their release SHA-256."""
import gzip
import hashlib
import io
import pathlib
import sys
import urllib.request
import zipfile


def fetch(url, digest):
    request = urllib.request.Request(url, headers={'User-Agent':'Leora-core-verification'})
    data = urllib.request.urlopen(request, timeout=90).read()
    if hashlib.sha256(data).hexdigest()!=digest:
        raise ValueError('Core checksum mismatch: '+url)
    return data


def main():
    dest = pathlib.Path(sys.argv[1])
    dest.mkdir(parents=True,exist_ok=True)
    mihomo = fetch('https://github.com/MetaCubeX/mihomo/releases/download/v1.19.32/mihomo-linux-amd64-v1.19.32.gz',
                   '8451100836c9eda194331c2babfad490b2faf30cebc1a04b0e76fd8ac2d35d10')
    path=dest/'mihomo';path.write_bytes(gzip.decompress(mihomo));path.chmod(0o755)
    xray=fetch('https://github.com/XTLS/Xray-core/releases/download/v26.3.27/Xray-linux-64.zip',
               '23cd9af937744d97776ee35ecad4972cf4b2109d1e0fe6be9930467608f7c8ae')
    # The GEOIP,CN fallback needs geoip.dat; Xray ships the canonical copy.
    archive=zipfile.ZipFile(io.BytesIO(xray))
    path=dest/'xray';path.write_bytes(archive.read('xray'));path.chmod(0o755)
    (dest/'geoip.dat').write_bytes(archive.read('geoip.dat'))
    print('Verified Mihomo 1.19.32 and Xray 26.3.27 release checksums')


if __name__=='__main__':main()
