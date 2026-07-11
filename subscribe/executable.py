import platform
import sys

from logger import logger


def which_bin() -> tuple[str, str]:
    cpu_arch = get_cpu_architecture()
    if cpu_arch not in ["amd", "arm"]:
        logger.error(f"subconverter does not support current cpu architecture: {cpu_arch}")
        sys.exit(1)

    operating_system = platform.system()
    if operating_system not in ["Windows", "Linux", "Darwin"]:
        logger.error(f"subconverter does not support current operating system: {operating_system}")
        sys.exit(1)

    if operating_system == "Windows" and cpu_arch != "amd":
        logger.error(f"the windows version of subconverter only supports amd64 architecture, current: {cpu_arch}")
        sys.exit(1)

    clashname = f"clash-{operating_system.lower()}-{cpu_arch}"
    subconverter = f"subconverter-{operating_system.lower()}-{cpu_arch}"

    if operating_system == "Windows":
        clashname += ".exe"
        subconverter += ".exe"

    return clashname, subconverter


def get_cpu_architecture() -> str:
    machine = platform.machine().lower()
    if machine in ("amd64", "x86_64", "x86-64", "x64"):
        return "amd"
    elif machine in ("arm64", "aarch64", "armv8l", "armv8"):
        return "arm"
    else:
        logger.error(f"unsupported cpu architecture: {machine}")
        sys.exit(1)
