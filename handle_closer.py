# -*- coding: utf-8 -*-
"""
Windows 跨进程句柄探测与安全关闭模块 (handle_closer.py)
利用 Windows Native API (NtQuerySystemInformation, DuplicateHandle, GetFinalPathNameByHandle)
在不终止目标进程的情况下，识别并安全关闭指定文件/目录的句柄。
"""

import os
import sys
import ctypes
from ctypes import wintypes
import logging

logger = logging.getLogger("HandleCloser")

# Windows API 常量
STATUS_INFO_LENGTH_MISMATCH = 0xC0000004
STATUS_SUCCESS = 0x00000000
SystemExtendedHandleInformation = 64

PROCESS_DUP_HANDLE = 0x0040
PROCESS_QUERY_INFORMATION = 0x0400
DUPLICATE_CLOSE_SOURCE = 0x00000001
DUPLICATE_SAME_ACCESS = 0x00000002

FILE_TYPE_DISK = 0x0001
FILE_NAME_NORMALIZED = 0x0

# 加载系统 DLL
ntdll = ctypes.WinDLL('ntdll')
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

class SYSTEM_HANDLE_TABLE_ENTRY_INFO_EX(ctypes.Structure):
    _fields_ = [
        ("Object", ctypes.c_void_p),
        ("UniqueProcessId", ctypes.c_size_t),
        ("HandleValue", ctypes.c_size_t),
        ("GrantedAccess", wintypes.ULONG),
        ("CreatorBackTraceIndex", wintypes.USHORT),
        ("ObjectTypeIndex", wintypes.USHORT),
        ("HandleAttributes", wintypes.ULONG),
        ("Reserved", wintypes.ULONG),
    ]

class SYSTEM_HANDLE_INFORMATION_EX(ctypes.Structure):
    _fields_ = [
        ("NumberOfHandles", ctypes.c_size_t),
        ("Reserved", ctypes.c_size_t),
        ("Handles", SYSTEM_HANDLE_TABLE_ENTRY_INFO_EX * 1),
    ]

# 设置 API 签名
ntdll.NtQuerySystemInformation.argtypes = [
    wintypes.ULONG,
    ctypes.c_void_p,
    wintypes.ULONG,
    ctypes.POINTER(wintypes.ULONG)
]
ntdll.NtQuerySystemInformation.restype = wintypes.ULONG

kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE

kernel32.GetCurrentProcess.restype = wintypes.HANDLE

kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL

kernel32.DuplicateHandle.argtypes = [
    wintypes.HANDLE,
    wintypes.HANDLE,
    wintypes.HANDLE,
    ctypes.POINTER(wintypes.HANDLE),
    wintypes.DWORD,
    wintypes.BOOL,
    wintypes.DWORD
]
kernel32.DuplicateHandle.restype = wintypes.BOOL

kernel32.GetFileType.argtypes = [wintypes.HANDLE]
kernel32.GetFileType.restype = wintypes.DWORD

kernel32.GetFinalPathNameByHandleW.argtypes = [
    wintypes.HANDLE,
    wintypes.LPWSTR,
    wintypes.DWORD,
    wintypes.DWORD
]
kernel32.GetFinalPathNameByHandleW.restype = wintypes.DWORD


def is_admin():
    """检查当前是否具备管理员权限"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def get_all_handles_for_pid(pid):
    """
    枚举指定进程的所有句柄信息列表
    """
    size = wintypes.ULONG(1024 * 1024 * 4)  # 初始 4MB 缓冲区
    return_len = wintypes.ULONG()

    while True:
        buf = ctypes.create_string_buffer(size.value)
        status = ntdll.NtQuerySystemInformation(
            SystemExtendedHandleInformation,
            buf,
            size,
            ctypes.byref(return_len)
        )
        if status == STATUS_INFO_LENGTH_MISMATCH:
            # 缓冲区不够，扩展大小重试
            size = wintypes.ULONG(return_len.value + 1024 * 512)
            continue
        elif status != STATUS_SUCCESS:
            logger.error(f"NtQuerySystemInformation failed with status: {hex(status)}")
            return []
        break

    # 解析 SYSTEM_HANDLE_INFORMATION_EX
    p_info = ctypes.cast(buf, ctypes.POINTER(SYSTEM_HANDLE_INFORMATION_EX))
    num_handles = p_info.contents.NumberOfHandles

    # 获取句柄条目指针数组首地址
    entries_ptr = ctypes.cast(
        ctypes.addressof(p_info.contents.Handles),
        ctypes.POINTER(SYSTEM_HANDLE_TABLE_ENTRY_INFO_EX)
    )

    matching_handles = []
    for i in range(num_handles):
        entry = entries_ptr[i]
        if entry.UniqueProcessId == pid:
            matching_handles.append(entry.HandleValue)

    return matching_handles


def get_handle_file_path(h_process, handle_value, current_process):
    """
    通过复制句柄到当前进程，查询磁盘文件完整路径。
    过滤掉非磁盘文件以避免在某些阻塞管道上 hang。
    """
    dup_handle = wintypes.HANDLE()
    success = kernel32.DuplicateHandle(
        h_process,
        wintypes.HANDLE(handle_value),
        current_process,
        ctypes.byref(dup_handle),
        0,
        False,
        DUPLICATE_SAME_ACCESS
    )
    if not success or not dup_handle.value:
        return None

    try:
        file_type = kernel32.GetFileType(dup_handle)
        # 仅针对磁盘文件进行路径解析，有效防止命名管道等挂起
        if file_type != FILE_TYPE_DISK:
            return None

        path_buf = ctypes.create_unicode_buffer(1024)
        length = kernel32.GetFinalPathNameByHandleW(
            dup_handle,
            path_buf,
            len(path_buf),
            FILE_NAME_NORMALIZED
        )
        if length == 0:
            # 当文件处于排他独占打开模式时，FILE_NAME_NORMALIZED 会失败，回退至 FILE_NAME_OPENED (0x8)
            length = kernel32.GetFinalPathNameByHandleW(
                dup_handle,
                path_buf,
                len(path_buf),
                0x8
            )

        if length > 0:
            path = path_buf.value
            # Windows 格式 \\?\C:\...
            if path.startswith("\\\\?\\UNC\\"):
                return "\\\\" + path[8:]
            elif path.startswith("\\\\?\\"):
                return path[4:]
            return path
        return None
    finally:
        kernel32.CloseHandle(dup_handle)


def find_locked_files_in_process(pid, target_folder=None):
    """
    获取指定进程中打开的所有文件及其句柄。
    如果提供了 target_folder，则只返回属于该文件夹的文件句柄。
    返回结构: list of dict -> [{'handle': int, 'path': str}]
    """
    results = []
    current_proc = kernel32.GetCurrentProcess()

    h_process = kernel32.OpenProcess(PROCESS_DUP_HANDLE | PROCESS_QUERY_INFORMATION, False, pid)
    if not h_process:
        logger.warning(f"无法打开目标进程 PID: {pid}，请检查权限。")
        return results

    try:
        handles = get_all_handles_for_pid(pid)
        target_folder_norm = os.path.abspath(target_folder).lower() if target_folder else None

        for hv in handles:
            path = get_handle_file_path(h_process, hv, current_proc)
            if not path:
                continue

            path_norm = os.path.abspath(path).lower()
            if target_folder_norm:
                if path_norm.startswith(target_folder_norm):
                    results.append({'handle': hv, 'path': path})
            else:
                results.append({'handle': hv, 'path': path})
    finally:
        kernel32.CloseHandle(h_process)

    return results


def close_remote_handle(pid, handle_value):
    """
    通过 DuplicateHandle(DUPLICATE_CLOSE_SOURCE) 安全关闭目标进程内的句柄
    """
    h_process = kernel32.OpenProcess(PROCESS_DUP_HANDLE, False, pid)
    if not h_process:
        err = ctypes.get_last_error()
        logger.error(f"无法打开进程 {pid} 进行句柄关闭，错误码: {err}")
        return False

    try:
        success = kernel32.DuplicateHandle(
            h_process,
            wintypes.HANDLE(handle_value),
            None,
            None,
            0,
            False,
            DUPLICATE_CLOSE_SOURCE
        )
        if not success:
            err = ctypes.get_last_error()
            logger.warning(f"关闭句柄 {hex(handle_value)} 失败，错误码: {err}")
            return False
        return True
    finally:
        kernel32.CloseHandle(h_process)
