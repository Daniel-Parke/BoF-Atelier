"""Ubuntu package qualification for the same private PCSX-Redux reference Lab."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile

from . import runtime_setup as runtime


BACKEND='pcsx-redux-linux'
RESOURCE='usr/share/pcsx-redux/resources/'
VERSION_DIGEST='d5f96bec0a5143b9bd578f2987cc0493efe06ee02c3e440da6eb03f6693e2ebe'


def component() -> dict:
    return runtime._catalogue()['pcsx-redux-linux-x64']


def check_host() -> None:
    if not sys.platform.startswith('linux') or platform.machine().lower() not in {'x86_64','amd64'}:
        raise runtime.RuntimeSetupError('This Lab package requires Ubuntu 24.04 on x86-64.')
    release=platform.freedesktop_os_release()
    if release.get('ID')!='ubuntu' or release.get('VERSION_ID')!='24.04':
        raise runtime.RuntimeSetupError('This reference build is currently qualified on Ubuntu 24.04 x86-64 only.')


def directory(private_root: Path) -> Path:
    return runtime._path(private_root,'lab','runtimes',BACKEND,component()['version'])


def verify(private_root: Path, *, full: bool=True) -> None:
    check_host()
    entry=component()
    stock=directory(private_root)
    image=runtime._path(stock,entry['package']['executable'])
    firmware=runtime._path(stock,'openbios.bin')
    version=runtime._path(stock,'version.json')
    if not runtime._path(stock,'.atelier-runtime.json').is_file() or not os.access(image,os.X_OK):
        raise runtime.RuntimeSetupError('Prepare the pinned official Ubuntu reference runtime in Lab.')
    expected={image:entry['package']['executable_sha256'],firmware:runtime._catalogue()['openbios-psx-rom']['member']['sha256'],version:VERSION_DIGEST}
    for path,digest in expected.items():
        if not path.is_file() or (runtime._digest(path)!=digest if full else not runtime._matches(path,digest)):
            raise runtime.RuntimeSetupError('The Ubuntu reference runtime or replacement firmware needs repair.')


def prepare(private_root: Path, source: Path|None=None) -> dict:
    """Stage only verified AppImage/ROM/version members; no FUSE, package manager or root is needed."""
    check_host()
    entry=component()
    package=entry['package']
    stock=directory(private_root)
    if source is not None:
        cache=runtime._cache_package(private_root,source,BACKEND,entry)
    else:
        cache=runtime._archive(private_root,BACKEND,entry)
    with runtime.reserve_idle_channel(private_root,'lab'):
        if not stock.exists():
            runtime._verify_download(cache,entry)
            stock.parent.mkdir(parents=True,exist_ok=True)
            if shutil.disk_usage(stock.parent).free < 2*package['bytes']+32*1024**2:
                raise runtime.RuntimeSetupError('Insufficient free space for the Ubuntu reference installation.')
            with tempfile.TemporaryDirectory(dir=stock.parent,prefix='.stage-') as temp:
                stage=Path(temp)
                ready=stage/'payload'
                ready.mkdir()
                image=ready/package['executable']
                with zipfile.ZipFile(cache) as archive:
                    entries=runtime._zip_entries(archive)
                    if len(entries)!=1 or entries[0].filename!=image.name:
                        raise runtime.RuntimeSetupError('The reviewed Linux ZIP must contain exactly the expected AppImage.')
                    with archive.open(entries[0]) as stream,image.open('xb') as output:
                        shutil.copyfileobj(stream,output,1024**2)
                if runtime._digest(image)!=package['executable_sha256']:
                    raise runtime.RuntimeSetupError('The AppImage differs from the reviewed Ubuntu package.')
                image.chmod(0o700)
                members={'openbios.bin':runtime._catalogue()['openbios-psx-rom']['member']['sha256'],'version.json':VERSION_DIGEST}
                for name,digest in members.items():
                    requested=RESOURCE+name
                    subprocess.run([str(image),'--appimage-extract',requested],cwd=stage,stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=60,check=True)
                    extracted=runtime._path(stage,'squashfs-root',*requested.split('/'))
                    if not extracted.is_file() or runtime._digest(extracted)!=digest:
                        raise runtime.RuntimeSetupError('An embedded Ubuntu runtime resource differs from the reviewed package.')
                    shutil.copyfile(extracted,ready/name)
                version=json.loads((ready/'version.json').read_text(encoding='utf-8'))
                if (version.get('version'),version.get('changeset'),version.get('buildId'))!=(entry['version'],package['source_commit'],package['release_id']):
                    raise runtime.RuntimeSetupError('The AppImage embedded identity differs from its official manifest.')
                runtime._atomic_json(ready/'.atelier-runtime.json',{'channel':'lab','backend':BACKEND,'version':entry['version'],
                                                        'sha256':package['sha256'],'files':{image.name:package['executable_sha256'],**members}})
                ready.rename(stock)
        verify(private_root)
    return {'backend':BACKEND,'channel':'lab','version':entry['version'],'executable':str(stock/package['executable']),'data_root':str(stock)}


def process_identity(pid: int) -> tuple[str,int]|None:
    if not isinstance(pid,int) or pid<1:
        return None
    process=Path('/proc')/str(pid)
    try:
        fields=(process/'stat').read_text(encoding='utf-8').rpartition(') ')[2].split()
        if fields[0]=='Z':
            return None
        return str((process/'exe').readlink()),int(fields[19])
    except (OSError,ValueError,IndexError):
        return None


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--private-root',type=Path,default=runtime.DEFAULT_PRIVATE)
    parser.add_argument('--source',type=Path,help='Optional unchanged official ZIP selected by its owner.')
    args=parser.parse_args()
    try:
        print(json.dumps(prepare(args.private_root,args.source),indent=2))
    except (OSError,ValueError,runtime.RuntimeSetupError,subprocess.SubprocessError) as error:
        parser.exit(1,str(error)+'\n')
