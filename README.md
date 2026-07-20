# Orca for Nix

[Orca](https://github.com/stablyai/orca) 是用于并行运行和管理编码代理的桌面应用。本仓库提供基于 Orca 官方二进制发布的 Nix flake。

当前打包版本：`1.4.146`

## 支持平台

| 平台 | 上游产物 | 状态 |
| --- | --- | --- |
| `x86_64-linux` | AppImage | 已构建并验证 CLI 与 GUI |
| `aarch64-linux` | AppImage | derivation 已求值 |
| `aarch64-darwin` | 官方 macOS ZIP | derivation 与应用包布局已验证 |

当前 Nixpkgs 26.11 已停止支持 `x86_64-darwin`，因此本 flake 不提供 Intel macOS 输出。需要 Intel macOS 时，应单独使用仍支持该平台的 `nixpkgs-26.05-darwin`。

## 使用

直接运行 CLI：

```bash
nix run .#orca-ide -- --help
```

安装到用户 profile：

```bash
nix profile install .#orca-ide
```

### Linux

```bash
orca-ide       # Orca CLI
orca-ide-gui   # Orca 桌面应用
```

桌面文件和图标会随包安装，可从桌面环境的应用菜单启动 Orca。

### Darwin

```bash
orca            # Orca CLI
orca-ide-gui    # Orca 桌面应用
```

应用包安装在：

```text
Applications/Orca.app
```

## 构建与检查

构建当前平台：

```bash
nix build .#orca-ide
```

检查所有声明的平台：

```bash
nix flake check --all-systems
```

检查 Nix 文件格式：

```bash
nix fmt -- --ci flake.nix package.nix
```

## 自动跟踪稳定版

更新工作流每小时检查一次上游稳定版，也可在 GitHub Actions 页面手动运行并通过可选的 `version` 输入指定版本。它还接受类型为 `orca-release` 的 `repository_dispatch` 事件；可选的 `client_payload.version` 用于指定版本，省略时检查最新稳定版。更新器只处理稳定版本，并直接使用 GitHub release asset 的 `digest` 更新各平台哈希，不跟踪预发布版本。

发现更新后，工作流会先验证修改，再执行构建和 CLI 冒烟测试；全部通过后才从固定分支 `automation/update-orca` 创建或更新 PR。若使用 `GITHUB_TOKEN` 创建 PR，需要在仓库的 **Settings → Actions → General → Workflow permissions** 中启用 **Allow GitHub Actions to create and approve pull requests**。

GitHub Actions 没有原生的跨仓库 release 事件。若希望接近实时地响应 `stablyai/orca` 发布，需要另行配置外部 GitHub App 或服务，在检测到发布后向本仓库发送 `repository_dispatch`；本仓库不假定该外部监听器已经配置。例如，可使用对 `Samuka007/nix-orca` 有访问权限且授予 **Contents: write** 的 fine-grained token：

```bash
curl --fail-with-body --request POST \
  --url https://api.github.com/repos/Samuka007/nix-orca/dispatches \
  --header "Accept: application/vnd.github+json" \
  --header "Authorization: Bearer <FINE_GRAINED_GITHUB_TOKEN>" \
  --header "X-GitHub-Api-Version: 2022-11-28" \
  --data '{"event_type":"orca-release","client_payload":{"version":"1.4.138"}}'
```

`client_payload.version` 可省略，此时工作流检查最新稳定版。

## Binary cache

该包会产生标准 Nix store output，可以上传到 Cachix 或其他 Nix binary cache。以 Cachix 为例：

```bash
export CACHIX_CACHE=your-cache-name

printf '%s' "$CACHIX_AUTH_TOKEN" \
  | nix run nixpkgs#cachix -- authtoken --stdin

out="$(nix build --no-link --print-out-paths .#orca-ide)"
nix run nixpkgs#cachix -- push "$CACHIX_CACHE" "$out"
```

也可以在构建期间自动上传新增 store paths：

```bash
nix run nixpkgs#cachix -- \
  watch-exec "$CACHIX_CACHE" -- \
  nix build .#orca-ide
```

## 打包说明

- Linux 使用 `appimageTools.wrapType2` 包装官方 AppImage。
- Linux 的 CLI 与 GUI 分开暴露，避免将 CLI 参数传给 Electron GUI。
- Darwin 安装官方签名的 `Orca.app`，并设置 `dontFixup = true`，避免破坏上游代码签名。
- 二进制来源标记为 `lib.sourceTypes.binaryNativeCode`。
- Orca 使用 MIT 许可证，官方二进制允许重新分发。

## Nixpkgs 上游贡献

Nixpkgs 已有名为 `orca` 的 GNOME 屏幕阅读器，因此本包使用上游 Linux 包名 `orca-ide`。提交到 Nixpkgs 时，package 文件应放置在：

```text
pkgs/by-name/or/orca-ide/package.nix
```

standalone flake 的 `flake.nix` 和 `flake.lock` 不应包含在 Nixpkgs PR 中。提交前还需要填写贡献者真实的 `meta.maintainers`。

## 上游

- Orca：https://github.com/stablyai/orca
- Releases：https://github.com/stablyai/orca/releases
