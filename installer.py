#!/usr/bin/env python3

import argparse
import os
import re
import subprocess
import sys

from pathlib import Path


class COLORS:
    CYAN = "\033[36m"
    GREEN = "\033[32m"
    RED = "\033[31m"
    BOLD = "\033[1m"
    END = "\033[0m"

    def cyan(s):
        return COLORS.CYAN + str(s) + COLORS.END

    def green(s):
        return COLORS.GREEN + str(s) + COLORS.END

    def red(s):
        return COLORS.RED + str(s) + COLORS.END

    def bold(s):
        return COLORS.BOLD + str(s) + COLORS.END


def parse_os_release():
    line_re = re.compile('^([A-Z_]*)="?(.*?)"?$')
    os_release_path = Path("/etc/os-release")
    os_release_dict = {}
    if os_release_path.is_file():
        content = os_release_path.read_text()
        for line in content.split("\n"):
            match = line_re.match(line)
            if match:
                os_release_dict[match.group(1)] = match.group(2)
    return os_release_dict


def get_os_id():
    return parse_os_release()["ID"]


def get_os_version_id():
    try:
        return parse_os_release()["VERSION_ID"]
    except KeyError:  # testing doesn't provides its version ID
        return None


def get_codename():
    if get_os_id() == "debian":
        os_version_id = get_os_version_id()
        if os_version_id is None:
            os_version_id = "12"  # force testing
        if os_version_id == "9":
            return "stretch"
        elif os_version_id == "10":
            return "buster"
        elif os_version_id == "11":
            return "bullseye"
        elif os_version_id == "12":
            return "bookworm"
        else:
            raise RuntimeError(
                COLORS.bold(COLORS.red("Unable to find Debian distro codename"))
            )
    elif get_os_id() == "ubuntu":
        if os_version_id == "20.04":
            return "focal"
        else:
            raise RuntimeError(
                COLORS.bold(COLORS.red("Unable to find Ubuntu distro codename"))
            )
    else:
        raise RuntimeError(COLORS.bold(COLORS.red("Unable to find Linux distribution")))


def get_package_list(path_list, codename, backports=False):
    if backports:
        codename += "-backports"
    # Get the list of package lists
    lists_list = []
    for p in path_list:
        if not backports:
            lists_list += list(p.glob("**/common.pkglist"))
        lists_list += list(p.glob("**/" + codename + ".pkglist"))

    # Get the package list from the lists
    package_list = []
    for l in lists_list:
        content = l.read_text()
        package_list += [
            package
            for package in content.split("\n")
            if package and not package.startswith("#")
        ]

    return package_list


def get_prehook_list(path_list, codename):
    # Get the list of hooks
    hook_list = []
    for p in path_list:
        hook_list += list(p.resolve().glob("**/common.prepkg.*"))
        hook_list += list(p.resolve().glob("**/" + codename + ".prepkg.*"))

    return hook_list


def get_posthook_list(path_list, codename):
    # Get the list of hooks
    hook_list = []
    for p in path_list:
        hook_list += list(p.resolve().glob("**/common.postpkg.*"))
        hook_list += list(p.resolve().glob("**/" + codename + ".postpkg.*"))

    return hook_list


def execute_subprocess(cmd, env=None):
    try:
        # TODO see how we could display progress, or give a way get progress
        # through a given file, or anything...
        subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, env=env
        )
    except PermissionError as e:
        print(
            COLORS.red(
                "Permission denied while executing %s. " % cmd
                + COLORS.bold("Is the file executable?")
            )
        )
    except subprocess.CalledProcessError as e:
        sys.stdout.flush()
        sys.stderr.flush()

        print(COLORS.red("Error in subprocess, aborting."))
        print(COLORS.bold("  cmd: ") + str(e.cmd))
        print(COLORS.bold("  return code: ") + str(e.returncode))

        if e.stdout:
            print(COLORS.bold("  stdout:"))
            print("%s" % e.stdout.decode("utf-8", errors="replace"))

        if e.stderr:
            print(COLORS.bold("  stderr:"))
            print("%s" % e.stderr.decode("utf-8", errors="replace"))

        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
This script will recursively search the provided folders for files
with the following patterns:
  * common.pkglist
  * common.prepkg.*
  * common.postpkg.*
  * <codename>.pkglist
  * <codename>-backports.pkglist
  * <codename>.prepkg.*
  * <codename>.postpkg.*

<codename> represents the distribution's codename, e.g. 'stretch', 'buster',
'focal', etc...

The *.pkglist files should contain one package name per line, and they will be
concatenated before calling the package manager. Comments are supported in the
form of lines starting with '#'.
The *.prepkg.* and *.postpkg.* files should be executable, and will be executed
before and after the call to the package manager, respectively.

Example:

$ tree deps
deps
|-- dev
|   |-- bullseye.pkglist
|   |-- buster.pkglist
|   |-- buster.postpkg.py
|   |-- buster.prepkg.sh
|   |-- buster-backports.pkglist
|   |-- common.pkglist
|-- runtime
    |-- buster.pkglist

With the tree above, one can call this script giving it the 'deps' folder to
install everything, or only the 'runtime' one to only install the runtime
dependencies.
""",
    )
    parser.add_argument(
        "folder",
        type=Path,
        nargs="+",
        help="A list of folder to search for dependencies list",
    )

    args = parser.parse_args()

    codename = get_codename()
    print(COLORS.cyan("distro codename: ") + codename, flush=True)

    prehook_list = get_prehook_list(args.folder, codename)
    package_list = get_package_list(args.folder, codename)
    package_backport_list = get_package_list(args.folder, codename, backports=True)
    posthook_list = get_posthook_list(args.folder, codename)

    if prehook_list:
        print(COLORS.cyan("running pre-packages hooks"), flush=True)
        for hook in prehook_list:
            execute_subprocess([str(hook)])

    if package_list or package_backport_list:
        print(COLORS.cyan("updating apt database"), flush=True)
        execute_subprocess(["apt", "update"])

    if package_list:
        print(COLORS.cyan("installing packages: ") + str(package_list), flush=True)
        env = os.environ.copy()
        env["DEBIAN_FRONTEND"] = "noninteractive"
        execute_subprocess(["apt", "install", "-y"] + package_list, env)

    if package_backport_list:
        print(
            COLORS.cyan("installing packages from backports: ")
            + str(package_backport_list),
            flush=True,
        )
        env = os.environ.copy()
        env["DEBIAN_FRONTEND"] = "noninteractive"
        execute_subprocess(
            ["apt", "install", "-t", codename + "-backports", "-y"]
            + package_backport_list,
            env,
        )

    if posthook_list:
        print(COLORS.cyan("running post-packages hooks"), flush=True)
        for hook in posthook_list:
            execute_subprocess([str(hook)])


if __name__ == "__main__":
    main()
