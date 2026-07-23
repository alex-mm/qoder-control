# Qoder Control 使用说明

这份文档给人看，用来说明如何从 Codex 调用本地 Qoder。

`SKILL.md` 是给 Codex/AI 执行时读的规则；这份 `USAGE.md` 是给你快速上手、排查问题、选择模式用的。

## 它能做什么

`qoder-control` 可以让 Codex 把任务发给本地 Qoder，并按不同方式处理结果：

- 同步后台模式：Codex 调用 `qodercli -p`，等待 Qoder 完成，拿到输出后再展示给你。
- 真异步模式：Codex 提交后立刻返回 `run_id`，Qoder 在后台跑，之后再查询状态。
- 分层产物：长任务会分别保存完整原始输出、精简总结和结构化发现，避免 Codex 默认读取大日志。
- YOLO 模式：后台模式的完全放权版本，Qoder 执行工具时不再要求权限确认。
- 终端输入模式：Codex 把 prompt 直接打进你当前打开的 Terminal，让你在终端里看 Qoder 输出。
- 桌面投递模式：使用 `qoder chat --reuse-window` 投递到 Qoder 桌面窗口，仅作为特殊 fallback。

核心脚本：

```bash
QODER_BRIDGE="$HOME/.codex/skills/qoder-control/scripts/qoder_bridge.py"
python3 "$QODER_BRIDGE"
```

## 第一次使用

先确认 `qodercli` 能被找到，并且已经登录：

```bash
QODER_BRIDGE="$HOME/.codex/skills/qoder-control/scripts/qoder_bridge.py"
python3 "$QODER_BRIDGE" status
```

重点看：

```json
{
  "preferred_qodercli": "/path/to/qodercli",
  "qodercli_candidates": [
    {
      "logged_in": true
    }
  ]
}
```

如果 `preferred_qodercli` 是 `null`，说明还不能用后台模式。你需要做下面任意一种：

```bash
command -v qodercli
qodercli login
```

或者显式指定路径：

```bash
export QODERCLI=/absolute/path/to/qodercli
QODER_BRIDGE="$HOME/.codex/skills/qoder-control/scripts/qoder_bridge.py"
python3 "$QODER_BRIDGE" --qodercli /absolute/path/to/qodercli status
```

不要依赖某个固定版本路径。技能会按这个顺序发现 `qodercli`：

1. 命令行参数 `--qodercli /absolute/path/to/qodercli`
2. 环境变量 `QODERCLI` 或 `QODERCLI_PATH`
3. `PATH` 里的 `qodercli`

## 模式选择速览

| 需求 | 推荐命令形态 | Codex 是否等待 Qoder 完成 | Codex 是否拿到输出 |
| --- | --- | --- | --- |
| 短问答、快速分析 | `send --wait` | 是 | 是 |
| 仓库 CR、PR review、长任务 | `send --detach` | 否 | 之后用 `check/show/wait` 取 |
| 明确授权的工程自动化 | `send --yolo` | 取决于是否加 `--detach` | 是 |
| 你想在 Terminal 看实时输出 | `send --transport terminal-input` | 否 | 否 |

重要区别：

- `--wait`：当前命令会等 Qoder 完成。
- `--detach`：当前命令只提交任务，立刻返回 `run_id`。
- `--yolo`：只控制是否绕过 Qoder 权限确认，不控制同步/异步。
- `--artifact-protocol`：要求 Qoder 写分层产物；`--detach`、`--yolo`、`app-chat` 会自动启用。
- 不加 `--wait` 也不加 `--detach`：命令仍会等 `qodercli -p` 进程结束，只是不额外轮询；这不是真异步。
- `--detach` 返回后，Codex 默认应该停止当前回合，只给你 `run_id` 和查询命令；只有你明确说“帮我盯着/等结果/继续查”，它才继续轮询。

## 结果文件

每次运行都会有一个目录：

```text
~/.codex/qoder-bridge/runs/<run-id>/
```

常用文件：

- `summary.md`：给 Codex 默认读取的精简结论。
- `findings.json`：结构化问题、测试结果、命令退出码等。
- `raw_output.txt`：完整原始输出、长日志、详细审查记录。
- `response.md`：兼容旧版本的最终回答，通常等同于 `summary.md`。
- `status.json`：完成状态。
- `stdout.txt` / `stderr.txt`：bridge 捕获到的进程输出。
- `user-prompt.md`：你最初发给 Qoder 的 prompt。
- `prompt.md`：实际发给 Qoder 的 prompt，长任务里会包含 mailbox 协议。

Codex 默认应该只读 `summary.md` 和 `findings.json`。只有需要复核、定位失败、或总结不够时，才读 `raw_output.txt`。

## 同步后台模式

适合：你想让 Codex 问 Qoder，然后由 Codex 把结果告诉你。

```bash
python3 "$QODER_BRIDGE" send \
  --wait \
  --cwd /path/to/project \
  "你好"
```

特点：

- 使用已登录的 `qodercli -p`
- 当前命令会等待 Qoder 完成
- Qoder 输出会被 Codex 捕获并展示
- 结果会写到 `~/.codex/qoder-bridge/runs/<run-id>/summary.md`，并保留 `response.md` 兼容旧流程
- 适合问答、短代码审查、快速分析任务
- 如果 Qoder 需要权限确认，非交互环境下可能失败或返回 blocked

## 真异步模式

适合：仓库 CR、PR review、长时间分析这类任务。提交后立刻返回，不占着当前 Codex 回合。

```bash
python3 "$QODER_BRIDGE" send \
  --detach \
  --transport qodercli \
  --yolo \
  --cwd /path/to/project \
  "请审查这个仓库，并输出高置信度问题"
```

返回示例：

```json
{
  "run_id": "20260723-091200-abcdef12",
  "detached": true,
  "state": "pending"
}
```

正确体验是：看到这个返回后，Codex 不再继续等待。你可以稍后再查，也可以明确要求 Codex 继续监控。

之后查询状态：

```bash
python3 "$QODER_BRIDGE" check <run-id>
python3 "$QODER_BRIDGE" show <run-id>
python3 "$QODER_BRIDGE" show --raw <run-id>
python3 "$QODER_BRIDGE" wait <run-id> --timeout 60
```

状态含义：

- `pending`：后台 worker 还在跑，或还没写出完成文件。
- `done`：Qoder 已完成，`summary.md` 或 `response.md` 可读。
- `error`：Qoder 或 bridge worker 失败。
- `blocked`：任务无法可靠完成，比如桌面投递没有写回 mailbox。

常用查询方式：

```bash
python3 "$QODER_BRIDGE" show <run-id>
python3 "$QODER_BRIDGE" check <run-id>
python3 "$QODER_BRIDGE" list --state pending
```

`show` 默认只打印元信息、状态、摘要、结构化发现和兼容回答。需要完整输出时：

```bash
python3 "$QODER_BRIDGE" show --raw <run-id>
python3 "$QODER_BRIDGE" show --all <run-id>
```

## YOLO 模式

适合：你明确授权 Qoder 执行本地自动化，比如跑命令、读写项目文件、直接做 PR review 评论。

```bash
python3 "$QODER_BRIDGE" send \
  --wait \
  --transport qodercli \
  --yolo \
  --cwd /path/to/project \
  "审查这个 PR，并直接评论高置信度问题"
```

`--yolo` 会传给 Qoder CLI：

```bash
--dangerously-skip-permissions
```

注意：

- 这会绕过 Qoder 的工具权限确认。
- 只在你信任当前任务和工作目录时使用。
- 不建议用于删除文件、修改凭据、处理敏感数据、或高风险外部操作。

Codex 使用技能时会按轻量规则自动选择是否加 `--yolo`：

- 会自动加：仓库/PR CR、跑测试、读取项目文件、例行 GitHub PR review/comment 这类边界清楚的工程自动化。
- 不会自动加：纯问答、概念解释、小型只读总结、`terminal-input`、`app-chat`。
- 会先问或不开：删除文件、改凭据/登录、改安全设置、访问大范围目录、发送敏感数据、金融/法律/高声誉风险外部沟通。

典型组合：

```bash
# 长任务：真异步 + 放权
python3 "$QODER_BRIDGE" send --detach --transport qodercli --yolo --cwd /path/to/project "审查这个 PR"

# 短只读问题：同步等待，不放权
python3 "$QODER_BRIDGE" send --wait --cwd /path/to/project "总结这个文件"
```

兼容旧写法：

```bash
--dangerously-skip-permissions
```

但日常推荐写：

```bash
--yolo
```

长任务通常这样组合：

```bash
python3 "$QODER_BRIDGE" send \
  --detach \
  --transport qodercli \
  --yolo \
  --artifact-protocol \
  --cwd /path/to/project \
  "审查这个 PR，并直接评论高置信度问题"
```

这里 `--artifact-protocol` 可以不写，因为 `--detach` / `--yolo` 会自动启用；显式写出来只是更好读。

## 终端输入模式

适合：你想亲眼在 Terminal 里看 Qoder 输出，而不是让 Codex 捕获输出。

先在 Terminal 里启动交互式 Qoder：

```bash
cd /path/to/project
qodercli
```

等它进入 Qoder 交互界面后，再让 Codex/脚本把 prompt 打进去：

```bash
python3 "$QODER_BRIDGE" send \
  --transport terminal-input \
  --cwd /path/to/project \
  "你好"
```

特点：

- prompt 会被输入到当前 Terminal 前台 tab
- Qoder 输出显示在 Terminal
- Codex 不捕获完整回答，只记录“已发送”
- 当前 Terminal tab 必须已经在交互式 `qodercli` 里

如果当前 Terminal tab 还在 shell prompt，`terminal-input` 会把 prompt 当 shell 命令执行。使用前先确认你看到的是 Qoder 的交互界面。

## 桌面投递模式

一般不推荐。它使用 Qoder 桌面 app 的 `qoder chat --reuse-window`：

```bash
python3 "$QODER_BRIDGE" send \
  --transport app-chat \
  --cwd /path/to/project \
  "你好"
```

这个模式更像“把消息投到桌面窗口”，不保证有 stdout，也不保证 Codex 能拿到回答。只有当你明确想操作 Qoder 桌面会话时再用。

## 常见问题

### `preferred_qodercli` 是 null

说明没找到已登录的 headless CLI。运行：

```bash
command -v qodercli
qodercli login
QODER_BRIDGE="$HOME/.codex/skills/qoder-control/scripts/qoder_bridge.py"
python3 "$QODER_BRIDGE" status
```

如果 `qodercli` 不在 `PATH`，设置：

```bash
export QODERCLI=/absolute/path/to/qodercli
```

### 后台模式遇到权限确认

同步后台模式和真异步模式都是非交互的。如果 Qoder 需要确认工具权限，可能返回：

```text
Permission confirmation required but no interactive handler is available
```

解决方式：

- 对低风险、明确授权的任务使用 `--yolo`
- 或改用终端输入模式，在 Terminal 里手动确认

### 终端上没输出

后台模式不会把输出打印到你打开的 Terminal。它会把 Qoder 输出捕获到 Codex 和 bridge run 目录。

如果你想在 Terminal 看输出，用 `terminal-input`，并确保 Terminal 当前 tab 已经进入交互式 `qodercli`。

### 怎么找到结果文件

每次 `send` 都会输出 run 目录，真异步模式也会立刻给出这个目录：

```text
~/.codex/qoder-bridge/runs/<run-id>/
```

常用文件：

- `user-prompt.md`：原始用户 prompt
- `summary.md`：默认读取的精简总结
- `findings.json`：结构化发现或测试结果
- `raw_output.txt`：完整原始输出或日志
- `response.md`：兼容旧流程的最终回答
- `status.json`：运行状态
- `metadata.json`：使用的 CLI、命令、时间等元信息

## 推荐选择

普通问答或分析：

```bash
python3 "$QODER_BRIDGE" send --wait "你的问题"
```

需要完全自动执行：

```bash
python3 "$QODER_BRIDGE" send --wait --transport qodercli --yolo "你的任务"
```

长任务后台执行：

```bash
python3 "$QODER_BRIDGE" send --detach --transport qodercli --yolo "你的任务"
```

想在 Terminal 里看实时输出：

```bash
python3 "$QODER_BRIDGE" send --transport terminal-input "你的问题"
```

排查环境：

```bash
python3 "$QODER_BRIDGE" status
```
