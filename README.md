# ArcGIS Pro 地理数据独占锁解除工具 | ArcGIS Data Lock Releaser

**[中文](#中文) | [English](#english)**

---

<a id="中文"></a>

# 中文文档

<p align="center">
  <img src="https://img.shields.io/badge/Platform-Windows-blue?logo=windows" alt="Platform">
  <img src="https://img.shields.io/badge/Python-3.8%2B-brightgreen?logo=python" alt="Python">
  <img src="https://img.shields.io/badge/ArcGIS%20Pro-2.x%20%2F%203.x-orange" alt="ArcGIS Pro">
  <img src="https://img.shields.io/badge/Data%20Types-File%20GDB%20%7C%20Shapefile-blueviolet" alt="Data Types">
  <a href="https://github.com/brildo/arcgis-data-lock-releaser/releases/latest">
    <img src="https://img.shields.io/badge/Download-Release%20v1.1.0-brightgreen?logo=windows" alt="Download">
  </a>
  <img src="https://img.shields.io/badge/License-MIT-green" alt="License">
</p>

---

## 📖 项目背景与解决的痛点

在日常 GIS 生产与数据处理工作中，**ArcGIS Pro** 对地理数据库（File Geodatabase，`.gdb`）和 Shapefile（`.shp`）通常采用**独占锁（Exclusive Lock）**或强句柄缓存机制。

- **常见痛点场景**：
  1. 用户在 ArcGIS Pro 中查看或编辑完数据后，已经在【内容】列表中**移除了图层**，甚至**关闭了地图或工程视图**；
  2. 但底层核心进程（`ArcGISPro.exe`）依然长期持有这些文件的 **Windows 底层操作系统文件句柄** 与 **`.lock` 锁文件**；
  3. 当第三方软件（如 QGIS、FME、PostgreSQL/PostGIS 导入工具、Python `geopandas` / `arcpy` 外部脚本）尝试以读写模式覆盖、重命名或更新该数据集时，必然遭遇权限错误；
  4. 此前的唯一解决办法是**彻底退出并关闭庞大的 ArcGIS Pro 进程**，严重打断多任务协同流。

**本工具专为解决该痛点而设计**：无需重启或关闭 ArcGIS Pro，即可精准探测哪些 GDB 或 Shapefile 正处于被锁状态，并在保证 Pro 进程平稳运行的前提下安全释放底层文件句柄。

### 🖼️ 软件界面展示

![ArcGIS Pro 数据锁解除工具 UI](UI.jpg)

*工具 GUI 显示被占用的数据集列表、文件句柄数量、锁文件状态等详细信息*

---

## ✨ 核心特性

- **非侵入式释放**：绝不暴力结束（Kill）ArcGIS Pro 主进程，仅针对目标数据集相关的底层文件句柄执行安全闭合，不影响 Pro 内正在进行的其他工程操作。
- **双主流地理格式支持**：
  - **File Geodatabase (`.gdb`)**：识别整个 GDB 文件夹结构与各子表文件句柄；
  - **Shapefile (`.shp`)**：智能反向聚合 `.shp`、`.dbf`、`.shx` 实体句柄及同级目录下的伴生锁文件（如 `*.shp.*.lock`）。
- **双重彻底解除**：
  1. 操作系统级：安全关闭 Windows 内核层面的打开文件句柄；
  2. 文件系统级：自动同步清理残留在目录下的孤立 `.lock` 文件。
- **即时读写独占性验证**：释放完成后内置独占性写测试，即时反馈外部是否已拥有完全写入权限。
- **现代化极简 GUI**：
  - 基于 Python 原生 Tkinter 开发，卡片式界面，清晰直观；
  - 支持自动巡检（每 5 秒自动检测最新占用状态）；
  - 支持单选释放、批量勾选释放与一键释放全部；
  - 支持一键在 Windows 资源管理器中定位目标文件。
- **绿色免依赖**：纯 Python + Windows Native API (ctypes) 打造，无需配置复杂的编译环境，双击即用。

---

## 🔬 技术实现原理

ArcGIS Pro 的数据占用由**两层机制**构成：
1. **`.lock` 状态标记文件**：GIS 软件内部用于标识读写状态（如 `*.sr.lock` 共享读锁、`*.ed.lock` 编辑锁）；
2. **Windows 内核文件句柄 (OS File Handle)**：阻碍外部写入和删除的根本原因。

```mermaid
flowchart TD
    A[启动检测] --> B[枚举 ArcGISPro.exe 及其子进程]
    B --> C[NtQuerySystemInformation 枚举系统句柄]
    C --> D[DuplicateHandle + GetFinalPathNameByHandleW 解析路径]
    D --> E{路径类型判断}
    E -->|含 .gdb 目录| F[聚合成 File GDB 记录]
    E -->|含 .shp/.dbf 或 *.shp.*.lock| G[聚合成 Shapefile 记录]
    F --> H[GUI 列表呈现占用状态]
    G --> H
    H -->|用户点击释放| I[DuplicateHandle + DUPLICATE_CLOSE_SOURCE]
    I --> J[内核安全关闭远程句柄]
    J --> K[清理磁盘残留 *.lock 锁文件]
    K --> L[执行独占读写验证并反馈结果]
```

通过 Windows Native 内核接口：
- `ntdll.NtQuerySystemInformation(SystemExtendedHandleInformation)`：高性能枚举指定进程句柄；
- `kernel32.DuplicateHandle(..., DUPLICATE_CLOSE_SOURCE)`：指示 Windows 内核在目标进程上下文内安全关闭指定句柄；
- 独占访问回退机制（`FILE_NAME_OPENED`）：确保处于排他独占状态的文件名亦能被完整解析。

---

## 📁 仓库文件结构

```
.
├── gdb_lock_resolver.py        # GUI 桌面主程序 (Tkinter)
├── lock_engine.py              # 锁检测、分析、聚合与解除核心引擎
├── handle_closer.py            # Windows 原生句柄探测与远程关闭底层模块 (ctypes)
├── test_lock_simulation.py     # 全流程自动化仿真测试脚本 (GDB & Shapefile)
├── run.bat                     # 通用启动脚本 (自动检测 Python 环境并以管理员提权)
├── 启动工具.vbs                # 静默一键启动器 (无 CMD 黑色控制台闪烁)
├── UI.jpg                      # 工具界面截图
├── requirements.txt            # Python 依赖清单
├── LICENSE                     # MIT 开源许可证
└── README.md                   # 仓库说明文档
```

---

## 🚀 快速上手

### 环境要求
- **操作系统**：Windows 10 / 11 / Windows Server (x64)
- **Python 环境**：Python 3.8 或更高版本（需包含 Tkinter，官方安装包默认自带）
- **权限要求**：Windows 管理员权限（跨进程句柄操作的 Windows 操作系统强制要求）

### 运行方式

#### 方式 1：直接运行打包好的独立单文件 EXE（最简便，无需安装 Python）
- 在 [**GitHub Releases 页面**](https://github.com/brildo/arcgis-data-lock-releaser/releases/latest) 直接下载最新版 **`ArcGIS_Data_Lock_Releaser.exe`**；
- 或在本地源码目录直接运行 **`dist\ArcGIS_Data_Lock_Releaser.exe`**；
- 采用 **Nuitka** 高性能 C 编译器直接转译打包，体积仅 ~9.6MB；
- 内嵌 UAC 管理员提权与 Tkinter 原生界面，完全无 CMD 黑色窗口闪烁，任何纯净 Windows 环境均可直接即开即用！

#### 方式 2：双击脚本启动（源码模式）
1. 双击运行 **`启动工具.vbs`**（基于 Windows 原生 WScript 静默启动，无任何黑框闪烁）；
2. 或双击运行 **`run.bat`**（会自动检查管理员权限并在唤起主程序后立即自动退出控制台窗口）。

#### 方式 3：命令行运行（开发者模式）
以管理员身份打开 PowerShell 或 CMD：
```powershell
# 切换至项目所在目录
cd /path/to/arcgis-data-lock-releaser

# 使用 pythonw 无窗口启动（或使用 python）
pythonw gdb_lock_resolver.py
```

---

## 💡 使用步骤与操作建议

1. **识别占用**：打开工具后，工具会自动检测系统中的 `ArcGISPro.exe` 进程并扫描被其占用的地理数据；
2. **选择目标**：在表格中查看数据集路径、数据类型、占用进程 PID、关联句柄数量以及锁文件数量；
3. **安全释放**：选中目标行，点击 **【释放选中数据锁】**；
4. **验证结果**：释放后可点击 **【验证选中数据读写】**，确认外部程序已完全恢复非只读访问权限。

> [!TIP]
> **最佳使用时机**：
> 建议在用户已在 ArcGIS Pro 中移除了该图层、关闭了相关地图、或已点击保存编辑内容之后使用本工具释放锁；
> 尽量避免在 ArcGIS Pro 正在执行长时间地理处理工具（正在写入该数据集）的过程中强行切断句柄。

---

## 🧪 自动化测试验证

项目中提供了完整的仿真测试脚本 `test_lock_simulation.py`，无需启动 ArcGIS Pro 即可验证端到端的核心解锁能力：

```powershell
python test_lock_simulation.py
```

**测试流程包括**：
- 自动构建模拟 File GDB 与 Shapefile 结构；
- 启动独立子进程以独占写模式锁定目标数据并创建模拟锁文件；
- 验证外部访问被死锁（报 PermissionError）；
- 调用核心引擎进行跨进程句柄定位与解除；
- 验证锁文件彻底清理、外部独占读写完全恢复；
- 确认目标进程全程存活，未发生崩溃。

---

## 📄 开源许可证

��项目遵循 [MIT License](LICENSE) 开源协议。欢迎提交 Issue 或 Pull Request 共建完善！

---

<a id="english"></a>

# English Documentation

<p align="center">
  <img src="https://img.shields.io/badge/Platform-Windows-blue?logo=windows" alt="Platform">
  <img src="https://img.shields.io/badge/Python-3.8%2B-brightgreen?logo=python" alt="Python">
  <img src="https://img.shields.io/badge/ArcGIS%20Pro-2.x%20%2F%203.x-orange" alt="ArcGIS Pro">
  <img src="https://img.shields.io/badge/Data%20Types-File%20GDB%20%7C%20Shapefile-blueviolet" alt="Data Types">
  <a href="https://github.com/brildo/arcgis-data-lock-releaser/releases/latest">
    <img src="https://img.shields.io/badge/Download-Release%20v1.1.0-brightgreen?logo=windows" alt="Download">
  </a>
  <img src="https://img.shields.io/badge/License-MIT-green" alt="License">
</p>

---

## 📖 Project Background & Pain Points Addressed

In daily GIS production and data processing workflows, **ArcGIS Pro** typically maintains **Exclusive Locks** or strong handle caching mechanisms on geographic databases (File Geodatabase, `.gdb`) and Shapefiles (`.shp`).

- **Common Frustrating Scenarios**:
  1. After viewing or editing data in ArcGIS Pro, users have already **removed the layer** from the Contents panel and even **closed the map or project view**;
  2. However, the underlying core process (`ArcGISPro.exe`) continues to hold **Windows OS file handles** and **`.lock` lock files** on these datasets;
  3. When third-party software (such as QGIS, FME, PostgreSQL/PostGIS import tools, or Python `geopandas`/`arcpy` external scripts) attempts to overwrite, rename, or update the dataset in read-write mode, it inevitably encounters permission errors;
  4. Previously, the only solution was to **completely exit and close the heavy ArcGIS Pro process**, severely disrupting multi-tasking workflows.

**This tool is specifically designed to solve this pain point**: Release locked file handles without restarting or closing ArcGIS Pro, while ensuring the Pro process continues running smoothly.

### 🖼️ Software Interface Preview

![ArcGIS Pro Data Lock Releaser UI](UI.jpg)

*Tool GUI displays list of occupied datasets, file handle counts, lock file status, and other detailed information*

---

## ✨ Core Features

- **Non-invasive Release**: Never forcefully kills the ArcGIS Pro main process. Only safely closes file handles related to the target dataset, without affecting other operations in Pro.
- **Dual Mainstream GIS Format Support**:
  - **File Geodatabase (`.gdb`)**: Identifies the entire GDB folder structure and all associated file handles;
  - **Shapefile (`.shp`)**: Intelligently aggregates `.shp`, `.dbf`, `.shx` file handles and companion lock files in the same directory (e.g., `*.shp.*.lock`).
- **Dual-Level Complete Release**:
  1. OS-level: Safely closes Windows kernel-level open file handles;
  2. File system-level: Automatically cleans up orphaned `.lock` files remaining in directories.
- **Real-time Read-Write Exclusivity Verification**: Built-in exclusive write test after release to immediately confirm external programs have full write access.
- **Modern Minimalist GUI**:
  - Developed with Python native Tkinter, card-style interface, intuitive and clear;
  - Supports auto-scanning (automatically detects occupancy status every 5 seconds);
  - Supports single selection release, batch multi-select release, and one-click release all;
  - Supports one-click location in Windows File Explorer.
- **Lightweight & Dependency-Free**: Built with pure Python + Windows Native API (ctypes), no complex compilation environment needed, just double-click to run.

---

## 🔬 Technical Implementation Details

ArcGIS Pro's data occupancy consists of **two mechanisms**:
1. **`.lock` Status Marker Files**: Used internally by GIS software to identify read-write states (e.g., `*.sr.lock` for shared read locks, `*.ed.lock` for edit locks);
2. **Windows Kernel File Handles (OS File Handle)**: The fundamental reason external write and delete operations are blocked.

```mermaid
flowchart TD
    A[Start Detection] --> B[Enumerate ArcGISPro.exe and child processes]
    B --> C[NtQuerySystemInformation to enumerate system handles]
    C --> D[DuplicateHandle + GetFinalPathNameByHandleW to resolve paths]
    D --> E{Path Type Judgment}
    E -->|Contains .gdb directory| F[Aggregate into File GDB record]
    E -->|Contains .shp/.dbf or *.shp.*.lock| G[Aggregate into Shapefile record]
    F --> H[Present occupancy status in GUI list]
    G --> H
    H -->|User clicks Release| I[DuplicateHandle + DUPLICATE_CLOSE_SOURCE]
    I --> J[Kernel safely closes remote handle]
    J --> K[Clean up orphaned *.lock files on disk]
    K --> L[Execute exclusivity verification and provide feedback]
```

Using Windows Native Kernel Interfaces:
- `ntdll.NtQuerySystemInformation(SystemExtendedHandleInformation)`: High-performance enumeration of process handles;
- `kernel32.DuplicateHandle(..., DUPLICATE_CLOSE_SOURCE)`: Instructs Windows kernel to safely close the specified handle in the target process context;
- Exclusive access fallback mechanism (`FILE_NAME_OPENED`): Ensures complete path resolution even for files in exclusive occupancy state.

---

## 📁 Repository Structure

```
.
├── gdb_lock_resolver.py        # GUI desktop main program (Tkinter)
├── lock_engine.py              # Lock detection, analysis, aggregation & release core engine
├── handle_closer.py            # Windows native handle detection & remote closure low-level module (ctypes)
├── test_lock_simulation.py     # End-to-end automated simulation test script (GDB & Shapefile)
├── run.bat                     # Universal startup script (auto-detects Python & elevates to admin)
├── 启动工具.vbs                # Silent one-click launcher (no CMD black console flashing)
├── UI.jpg                      # Tool interface screenshot
├── requirements.txt            # Python dependency list
├── LICENSE                     # MIT Open Source License
└── README.md                   # Repository documentation
```

---

## 🚀 Quick Start

### System Requirements
- **Operating System**: Windows 10 / 11 / Windows Server (x64)
- **Python**: Python 3.8 or higher (must include Tkinter, included by default in official installers)
- **Permissions**: Windows Administrator rights (required by Windows OS for cross-process handle operations)

### Running Methods

#### Method 1: Run Packaged Standalone EXE (Simplest, No Python Installation Required)
- Download the latest **`ArcGIS_Data_Lock_Releaser.exe`** from the [**GitHub Releases page**](https://github.com/brildo/arcgis-data-lock-releaser/releases/latest);
- Or run **`dist\ArcGIS_Data_Lock_Releaser.exe`** directly in your local source directory;
- Compiled with **Nuitka** high-performance C compiler, only ~9.6MB in size;
- Includes UAC admin elevation and native Tkinter interface; completely free of CMD black window flashing; works immediately on any clean Windows environment!

#### Method 2: Double-Click Script Launch (Source Code Mode)
1. Double-click **`启动工具.vbs`** (silent launch based on Windows native WScript, no black window);
2. Or double-click **`run.bat`** (auto-checks admin permissions and auto-closes console after launching the main program).

#### Method 3: Command Line Launch (Developer Mode)
Open PowerShell or CMD as Administrator:
```powershell
# Navigate to the project directory
cd /path/to/arcgis-data-lock-releaser

# Launch with pythonw (or python)
pythonw gdb_lock_resolver.py
```

---

## 💡 Usage Steps & Recommendations

1. **Identify Occupancy**: After opening the tool, it automatically detects the `ArcGISPro.exe` process and scans geospatial data it occupies;
2. **Select Targets**: View dataset paths, data types, occupying process PID, associated handle counts, and lock file counts in the table;
3. **Safe Release**: Select target row(s) and click **【Release Selected Data Locks】**;
4. **Verify Results**: After release, click **【Verify Selected Data Read-Write】** to confirm external programs have full non-read-only access.

> [!TIP]
> **Best Time to Use**:
> Use this tool after you've removed the layer from ArcGIS Pro, closed the related map, or saved your edits;
> Avoid forcefully disconnecting handles while ArcGIS Pro is executing long-running geoprocessing tools that are writing to the dataset.

---

## 🧪 Automated Testing & Validation

The project includes a complete simulation test script `test_lock_simulation.py`. Verify end-to-end lock release capabilities without launching ArcGIS Pro:

```powershell
python test_lock_simulation.py
```

**Test Flow Includes**:
- Automatically builds mock File GDB and Shapefile structures;
- Launches independent subprocess to exclusively lock target data in write mode and create simulated lock files;
- Verifies external access is blocked (PermissionError thrown);
- Invokes core engine to locate and release cross-process handles;
- Verifies lock files are completely cleaned up and external read-write access fully restored;
- Confirms target process remains alive throughout, no crashes.

---

## 📄 Open Source License

This project is licensed under the [MIT License](LICENSE). We welcome Issues and Pull Requests for collaborative improvement!

---

## 🤝 Contributing

Contributions are welcome! Whether you've found a bug, have a feature request, or want to improve the documentation, please feel free to open an Issue or submit a Pull Request.

## 📞 Support

If you encounter any issues, please open an [Issue](https://github.com/brildo/arcgis-data-lock-releaser/issues) on GitHub and provide:
- Your Windows version
- Python version
- ArcGIS Pro version
- Detailed description of the problem
- Relevant error messages or logs
