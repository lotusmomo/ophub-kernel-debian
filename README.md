# ophub-kernel-debian

为 **Vanilla Debian** 提供 ophub 内核的原生 Debian 软件包和签名 APT 仓库。

本项目将 [ophub/kernel](https://github.com/ophub/kernel) 发布的 ARM64 内核
tarball 重打包为 `.deb`，使原版 Debian 可以使用 ophub 内核，并继续通过
`apt`、`dpkg`、`initramfs-tools` 和 Debian 的内核维护钩子管理安装、更新和卸载。
它提供的是内核软件包，不是完整系统镜像，也不要求更换 Debian 用户空间。

## 提供的功能

- 跟踪 ophub `kernel_stable` 中的最新 **6.12.y** 内核。
- 打包内核 Image、模块、配置、System.map 和上游 Amlogic DTB。
- 提供 `linux-image-arm64` 元包，通过 APT 跟随新的内核版本。
- 保留上游内核 release 和模块 ABI，不把 ophub 内核伪装成 Debian 官方 ABI。
- 使用目标 Debian 系统的原生钩子生成 initramfs，并与 `u-boot-menu` 集成。
- 生成带 GPG 签名的 Flat APT Repository，支持 deb822 格式的源配置。
- 使用 GitHub Actions 检测上游更新、构建软件包并同步 GitHub Releases。
- 保留已发布的软件包和版本快照，允许选择旧内核恢复启动。
- 提供可选板级启动配置；通用元包不会自动选择任何板型。

软件包不刷写 U-Boot、BL2、BL31 或其他固件，不修改磁盘分区表，也不写入
eFuse、OTP 或 eMMC 永久配置。现有引导链和磁盘布局由设备管理员管理。

## 适用范围

当前目标是运行原版 Debian 的 **ARM64 Amlogic 设备**，使用 ophub 通用
stable 内核及 Amlogic DTB 集合。硬件支持范围取决于上游内核、驱动和具体板子的
设备树；不代表所有 Amlogic 型号都能直接安装后启动。

使用前需要具备可加载 ARM64 Linux Image、initramfs 和 DTB 的引导程序，
并为自己的设备准备正确的 DTB、根文件系统参数和恢复入口。不同型号的板级
配置不能互换。Rockchip、Allwinner、其他内核系列及 x86 不属于当前打包范围。

当前不提供内核 headers、DKMS 或自行编译第三方模块的支持。依赖这些功能的
系统应先解决相应模块的兼容性，再切换内核。

## 软件包

| 软件包 | 用途 |
| --- | --- |
| `linux-image-<kernel-version>-ophub` | 一个具体版本的内核、模块、配置和设备树 |
| `linux-image-arm64` | 精确依赖当前 ophub 内核包的跟踪元包 |
| `m13-boot-support` | 可选的天猫魔盒 M13 DTB 选择和 U-Boot 菜单默认值 |

例如，内核 `6.12.112-ophub` 的包版本为 `6.12.112-1+ophub.<revision>`。
`linux-image-arm64` 使用 epoch `1:`，便于从 Debian 官方元包切换到这个源。
版本化的内核包可以与原有 Debian 内核共存，不会覆盖旧版本的内核和模块。

通用构建默认生成前两个包。发布工作流还生成可选的 M13 support 包，但
`linux-image-arm64` 不依赖或推荐它；只有 M13 用户才应显式安装它。
板级配置详见 [board profiles](docs/board-profiles.md)。

## 添加 APT 源

以下示例适用于仓库的 `apt-6.12` Release 已发布、且可以匿名下载的情况。
私有仓库不能直接作为此示例中的公共 APT 下载源。

先下载公钥到临时文件，并核对指纹：

```sh
curl -fL https://github.com/lotusmomo/ophub-kernel-debian/releases/download/apt-6.12/archive-keyring.gpg \
    -o /tmp/ophub-kernel.gpg
gpg --show-keys --with-fingerprint /tmp/ophub-kernel.gpg
```

仓库签名公钥指纹：

```text
D6FB 1FB4 2E25 19BD 2559 DBBF 88A4 C116 2D7E 5DCD
```

确认指纹一致后安装公钥：

```sh
sudo install -D -m 0644 /tmp/ophub-kernel.gpg /etc/apt/keyrings/ophub-kernel.gpg
sudoedit /etc/apt/sources.list.d/ophub-kernel.sources
```

在 `ophub-kernel.sources` 中填写：

```text
Types: deb
URIs: https://github.com/lotusmomo/ophub-kernel-debian/releases/download/apt-6.12/
Suites: ./
Architectures: arm64
Signed-By: /etc/apt/keyrings/ophub-kernel.gpg
Enabled: yes
```

然后更新索引并查看候选版本：

```sh
sudo apt-get update
apt-cache policy linux-image-arm64
```

不要使用 `trusted=yes`、`--allow-unauthenticated` 或关闭签名检查。
本地目录及 NFS 挂载目录的源配置见 [本地 APT 仓库](docs/local-apt.md)。

## 安装与更新

安装前保留一个已验证能够启动的旧内核，确认 DTB、initramfs 和根分区参数，
并准备串口或其他恢复方式。对于 U-Boot/extlinux 系统，先阅读
[启动集成](docs/boot-integration.md)。

```sh
sudo apt-get -s install linux-image-arm64
sudo apt-get install linux-image-arm64
```

安装时会执行 Debian 的内核维护钩子，运行 `depmod` 并在目标系统生成 initramfs。
如果 initramfs 或其他关键钩子失败，软件包配置会失败，不会继续提升启动菜单。
安装完成后检查 `/boot` 中的 Image、initramfs、DTB 和实际启动菜单，再重启验证。

后续更新仍通过 APT 进行：

```sh
sudo apt-get update
sudo apt-get install linux-image-arm64
```

保留旧的版本化内核包，直到新版本启动和设备功能验证完成。软件包不会自动
重启机器。恢复 Debian 官方内核和元包的步骤见 [回退说明](docs/rollback.md)。

## 本地构建

构建环境需要 Linux、Python 3.12 或更新版本，以及 Debian 打包和签名工具：

```sh
sudo apt-get install python3 dpkg-dev apt-utils gnupg kmod
git clone https://github.com/lotusmomo/ophub-kernel-debian.git
cd ophub-kernel-debian
PYTHONPATH=src python3 -m ophub_kernel.cli check-upstream
PYTHONPATH=src python3 -m ophub_kernel.cli build \
    --output .cache/packages-generic-1 --revision 1
```

这只生成软件包，不安装内核，也不访问目标设备。构建时校验上游资产的 SHA-256、
内部 tarball 校验和、ARM64 Image 格式、内核 release 和每个模块的 vermagic。
提取流程拒绝路径穿越、重复文件及不允许的链接或特殊文件。

为构建产物生成签名仓库：

```sh
PYTHONPATH=src python3 -m ophub_kernel.cli repository \
    --packages .cache/packages-generic-1 --output wwwroot \
    --signing-home /path/to/private-signing-home --fingerprint PUBLIC_FINGERPRINT
```

也可以用 `scripts/build-local.sh` 完成构建和签名：

```sh
bash scripts/build-local.sh 1 /path/to/private-signing-home PUBLIC_FINGERPRINT
```

签名目录必须仅允许其所有者访问，并且位于 `wwwroot` 之外。私钥、下载缓存和
临时构建目录不属于公开产物。输入、板级 profile 或打包代码变化时，应使用新的
包 revision；revision 在所有 profile 间共用，不因缓存目录不同而重新计数。
不会覆盖已存在的同版本软件包。

`wwwroot/` 包含 `.deb`、Packages 索引、Release、InRelease、Release.gpg、
公钥、构建 manifest、SHA256SUMS 和源配置示例，可由静态服务器提供下载。

## 自动同步与测试

GitHub Actions 每小时检查一次上游 stable 6.12.y 资产。版本、资产摘要、
更新时间、打包代码或启用的板级 DTB 变化时生成新的 revision；没有变化时，
定期刷新有有效期的签名索引。

`apt-6.12` Release 提供稳定的 Flat Repository 地址；
`kernel-<release>-r<revision>` Release 保存不可变版本快照。
配置签名 Secrets 和发布规则见 [Release 同步](docs/github-release.md)。

运行测试需要额外安装 C 编译器；维护钩子测试使用隔离 chroot，需要 root
或可用的非交互式 `sudo`：

```sh
sudo apt-get install gcc
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## 上游与许可证

- [ophub/kernel](https://github.com/ophub/kernel)：内核发布资产及源码说明。
- [amlogic-s9xxx-armbian](https://github.com/ophub/amlogic-s9xxx-armbian)：上游设备支持和内核构建工具。
- [unifreq/linux-6.12.y](https://github.com/unifreq/linux-6.12.y)：6.12.y 内核源码参考。

内核及模块遵循 Linux 上游 GPL-2.0 许可；打包工具为 GPL-2.0-only。
设备树沿用其原有许可证。软件包保留内核配置、来源链接和构建输入摘要，
不修改内核 release 或模块 ABI。本项目不是 Debian 官方内核，也不是 ophub 官方 Debian 仓库。
