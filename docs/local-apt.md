# 本地 Flat APT 仓库

构建和签名产物统一放在 `wwwroot/`，可通过 HTTPS 静态服务器、普通本地
目录或只读 NFS 挂载提供给 Debian。私钥目录和构建缓存不得导出。

先核对并安装公开签名 keyring，再创建 deb822 文件：

```text
Types: deb
URIs: file:/mnt/ophub-kernel/
Suites: ./
Architectures: arm64
Signed-By: /etc/apt/keyrings/ophub-kernel.gpg
Enabled: yes
```

其中 `/mnt/ophub-kernel/` 应是已有的仓库目录或挂载点。APT 使用 `file:`
读取本地目录，不使用 `nfs:` URI。确认 `_apt` 用户可以读取目录、索引和包。
NFS export 可限制为指定客户端，并使用 `ro,sync,no_subtree_check,root_squash`。

更新这个源时，如需限定检查范围，保留其他来源的现有索引：

```sh
sudo apt-get update \
    -o Dir::Etc::sourcelist=/etc/apt/sources.list.d/ophub-kernel.sources \
    -o Dir::Etc::sourceparts=- \
    -o APT::Get::List-Cleanup=false --error-on=any
```

首次安装前仍应运行完整的正常 `apt-get update`，让 Debian 原有源和依赖
索引保持有效。临时挂载用完后先把源的 `Enabled` 改成 `no`，再卸载目录。
正常启动和恢复启动不应依赖 APT 仓库服务器在线。

切换到 GitHub 时只更改 `URIs`；保留已独立核对的签名 keyring，不关闭认证。
