# ticket watch

仓库：[Scr169/sissi-ticket-watch](https://github.com/Scr169/sissi-ticket-watch)。

正式监控 **An Oak Tree（Suranne Jones指定场）、Virginia Woolf（所有尚未开演场次）** 的官方票源。Virginia Woolf于2026-11-10按用户要求从仅当天扩展至全部未来场次。Lear于2026-11-05按用户要求停止；Eurotrash已停止，Golden Boy已移除，The Hungry Ghost已结束。RSC保持未启用。JCS云端未启用，本地定时任务也已因用户担心Codex额度而暂停。电脑可以关机。只提醒，不登录剧院、不占座、不加购物车、不购买。

## 独立调度与停跑告警

主调度器是私有 **Google Apps Script**：dispatchChecks 时间触发器每五分钟调用 GitHub workflow_dispatch，由标准公共 Linux runner 执行官方查票和浏览器核验。GitHub 原 cron 保留为备用；它曾出现约七小时空档，配置间隔不能当成实际执行频率。

第二个 Google 时间触发器 watchdog 检查各剧目状态的真实读取时间。只有所有仍在演出的剧目都有新的成功读取，才向另一家云服务 **Healthchecks.io** 发健康心跳。任务已排队、绿色工作流、旧成功结果，或只有一部剧更新，都不能反复刷新健康状态。Healthchecks 超过五分钟预期间隔加十分钟宽限未收到新心跳会发送异常邮件，Google 整体停止时仍能告警。

免费服务没有无延迟保证。查看 Actions 实际运行记录、状态中的 last_checked_at 和 Healthchecks 心跳记录；短于检查间隔的变化仍可能错过，发现放票也不保证最终能买到。

## 官方票源与结束时间

| 剧目 | 官方来源 | 监控至（伦敦时间） | 状态文件 |
| --- | --- | --- | --- |
| Eurotrash（用户已停止） | 2026-11-04按用户要求移除自动检查、测试通知入口和健康列表；独立启动monitor.py也不再查票，保留其他剧目共用函数 | 已停止，不再查票或提醒 | monitor-state.json（历史） |
| Golden Boy（已移除） | 用户于2026-11-01要求停止；工作流和私有调度已移除，历史记录保留 | 已结束，不再检查或提醒 | golden-boy-state.json（历史） |
| An Oak Tree / Suranne Jones | The Other Palace官方Spektrix公开票源，仅240703 / 2026-11-15 15:00，正向信号再次排除专属锁座 | 2026-11-15 15:00开演 | an-oak-tree-state.json |
| Who’s Afraid of Virginia Woolf?（所有未来场次） | @sohoplace完整官方日历，按Europe/London排除已开演场次；正向信号逐场打开对应官方nLiven票页确认 | 所有未来日期至2026-12-19结束 | virginia-woolf-state.json；scope=all_future |
| The Hungry Ghost | Bush Theatre官方Spektrix Studio公开场次与库存；空价格带另查明确普通票数，正向信号核对排除专属票的普通库存 | 2026-10-31 20:00最后一场开演 | hungry-ghost-state.json |
| Lear（Ian McKellen，用户已停止） | 2026-11-05移除自动工作流和私有健康列表；独立启动yard_lear.py也不查票，历史记录保留 | 已停止，不再查票或提醒 | lear-state.json（历史） |
| As You Like It（RSC，未启用） | 普通本机浏览器可读；19:39云端重试确认官方售票页由Imperva要求真人验证码。未解验证码或绕过，保留手动诊断rsc_probe，不参加正式调度/健康心跳 | 仅11月6日19:30、11月7日13:30及19:30；排除11月5日，11月7日19:30后结束 | rsc-as-you-like-it-state.json（尚未建立成功云端状态） |
| 田馥甄《要去什麼地方》（未启用） | 本机公开读取成功；GitHub云端HTTP返回403/CloudFront，普通Chrome完整页面也未读到六场有效状态；仅保留手动诊断，排除正式心跳 | 需求范围：台北2026-12-12至12-20全部6场 | hebe-state.json（unknown） |
| JCS On-Stage Standing（未启用） | 普通本地浏览器可打开舞台票区；两次GitHub云端Chrome被官网拒绝验证，不能判断库存。仅保留手动诊断，不参加正式心跳 | 需求范围：2026-10-31及之前 | jcs-on-stage-state.json（unknown） |

Eurotrash 官网曾展示 58 项，公开 API 返回 55 场。未返回项包括 Press Night 和 12 月 2 日两场，后两场原因未确认；尚未验证与官网全部场次完全一致。每次重新读取公开列表，不能承诺未公开场次的库存覆盖。

Golden Boy 官方日历表单与脚本使用 WordPress event 11278，官方售票 production 为 8745。2026-10-19 捕捉到 10 月 24 日 14:00 的 Book Tickets / Limited availability，并邮件提前提醒；打开售票页时明确显示 Sold Out，没有宣称确认有票。真实开放按钮内多出的辅助 time 标签已加入回归测试，日期只采用带 datetime 的场次时间。

## 两级提醒与去重

邮件标题和预览先显示剧目名，例如 `Eurotrash｜有票了`、`田馥甄《要去什麼地方》｜购票入口变化，余票待核实`、`An Oak Tree（Suranne Jones）｜有票了`、`Virginia Woolf（仅当天）｜有票了`、`The Hungry Ghost｜有票了`、`Lear（Ian McKellen）｜有票了`。GitHub通知邮件会另加仓库前缀。异常、恢复和测试通知也采用剧名在前的格式。

1. **【购票入口变化，余票待核实】**：官方场次出现公开购票链接或票源正向信号就先提醒，随后继续核验。价格和实际余票未确认时明确说明。
2. **【放票提醒】有票了**：再次验证至少一张普通公开可选票/座位后补发确认。只有入口按钮不够；会员、邀请或 Access 专属库存不算普通公开票。Audio Described 或 Relaxed 场次本身不等于专属票。

同一持续信号去重；官方场次确实关闭后重新出现再提醒。提前通知和确认通知分别去重。提醒包含伦敦时间、演出时间、官方直达链接和余票可能随时售出的说明。GitHub issue @提及账户所有者，经其已验证邮箱接收；手机开启 Gmail 新邮件或 GitHub Mentions 通知。

## 故障与时间记录

- 页面错误、验证码、空列表、无法识别的数据、缺少公开座位证据均为 unknown，不能当售罄。
- 连续三次读取失败，单独发“监控异常，不是放票”；恢复后提醒一次。各剧目分开记录。
- last_attempt_at 是实际尝试时间；last_checked_at 只在成功核实本轮状态后更新；last_source_read_at 表示读到了票源信号。last_state_change 不能代替检查时间。
- 独立 watchdog 另检查真实尝试是否超过十五分钟；Healthchecks 监测新的健康结果是否中断。报警演练使用单独、明确标为测试的 check，正式查票持续运行。
- 2027-01-10 自动暂停正式 Healthchecks check 并删除本项目两个 Google 时间触发器，避免演出结束后误报警。

## 私有凭据与停止

公开代码不含个人邮箱、密码或令牌。Google 脚本仅请求联网与无人值守执行，不读取 Gmail。GitHub fine-grained token 仅限本仓库：Actions 写、Contents 读、Issues 写和必需 Metadata 读，2027-01-11 到期。它与 Healthchecks 项目凭据只存 Google 私有 Script Properties，已获用户明确授权；2026-10-21用户要求在同一项目增加以下三个监控，不扩大令牌权限。

完整停止需删除 Google 项目的 dispatchChecks 和 watchdog 两个触发器、暂停 Healthchecks 正式 check，并停用 GitHub 工作流。只停 GitHub 会触发预期故障告警。原来依赖电脑的本地任务保持暂停。

## 验证

运行 python3 -m unittest discover -s tests -v，以及 node --test tests/test_scheduler.cjs。

96 个 Python 测试覆盖官方来源、真实售罄/开放形态、公开座位核验、早期提醒顺序、去重、失败重试和实际读取时间。14 个调度器测试覆盖排队不等于检查、旧结果不能续命、只部分剧目更新不算全体健康、停跑和调度失败。Virginia Woolf新增范围包含未来日期、末日场次、夏令时和旧当天状态迁移的去重验证。

RSC于2026-11-05申请接入；用户随后排除当天。production 62239剩余62530 / 11月6日19:30、62573 / 11月7日13:30、62531 / 11月7日19:30。读取器已实现完整场次覆盖、普通Full Price座位核验及不选座的票区查看；£18无障碍价格不作普通票价。云端直接日历和官网Book Tickets正常导航两次试读均未加载有效列表，因此当前未启用。RSC_DIAGNOSTIC=true仅手动试读；独立启动也默认关闭，须另行验证成功后才可设置RSC_ACTIVE=true并接入正式工作流及私有FEEDS。未创建任何新的本地/Codex定时任务。

2026-11-05 19:39再次从官网正常入口在GitHub普通Chrome读取，外层为空白，但公开iframe明确显示Imperva的“Additional security check is required”。本轮只读取错误页面，没有点击验证码、导入cookie或更改浏览器指纹。RSC仍未启用；本机手动新加载官网的11月6日/7日三场均显示Sold Out。Lear已经按用户要求停止，正式监控只剩Suranne和Virginia Woolf当天。

Bush《The Hungry Ghost》于2026-10-29新增，任意未来日期和公开票价，截止10月31日20:00。官网四场日期时间与官方API逐一匹配。29日20:00的availability为空价格带，必须另查instance status的明确available值，不能以空列表当零库存。标准官网列价£25，退票实际价格未由库存证实则仍写未知。

The Yard《Lear》于2026-10-29新增，任意未来日期和公开票价。39场官方售票日历与API实例ID逐一匹配，包括2027-01-02 14:30和19:30。查询name=Lear也会返回Lear: The Gala，严格排除后者。普通available再次核验不包括Access/特殊/会员锁座；官网提示用户需自行登录后选座，监控不登录。实际退票价格未证实则写未知，官网另有£150–£300 Legend票，任意公开票价范围包含这些票。

## 官方依据

- [The Yard Lear](https://www.theyardtheatre.co.uk/events/lear)
- [Bush Theatre The Hungry Ghost](https://www.bushtheatre.co.uk/event/the-hungry-ghost/)
- [Young Vic Eurotrash](https://www.youngvic.org/whats-on/eurotrash/)
- [Almeida Golden Boy](https://almeida.co.uk/whats-on/golden-boy/) · [官方退票指引](https://almeida.co.uk/how-to-get-tickets-to-golden-boy/)
- [Google 定时器](https://developers.google.com/apps-script/guides/triggers/installable) · [免费配额](https://developers.google.com/apps-script/guides/services/quotas)
- [GitHub 定时任务可能延迟或丢弃](https://docs.github.com/en/actions/how-tos/troubleshoot-workflows)
- [Healthchecks 免费方案](https://healthchecks.io/pricing/) · [故障心跳机制](https://healthchecks.io/docs/)

## 新增监控的范围与负载

每五分钟仍只启动一个工作流，正式检查未结束的项目；Golden Boy已移除，The Hungry Ghost按截止时间自动结束。Suranne的日常售罄检查只需少量公开只读请求。Woolf仅检查伦敦当天：未来日期的余票及购票页不核验；官方整轮日历有效但今天没有剩余演出时记录no_performances_today并安静待机，仍属于健康检查。空日历、页面错误与无法验证库存仍记unknown。伦敦午夜和夏冬令时切换由Europe/London处理。此流程在GitHub/Google云端执行，不消耗Codex本地定时额度。JCS诊断代码会用普通Chrome逐场打开舞台票区，但目前未通过云端加载，默认不运行；仅手动勾选jcs_probe可再次诊断，失败作业会明确变红。各剧目独立状态、去重和连续失败告警；新增网站失败不应阻止已完成的其他剧目结果保存。全体健康心跳必须包括每个尚未结束的监控。

只开票区、不改变票数、不点实际座位、不点Update Basket、不接受On-stage Standing Agreement。遇到验证码或未识别票种时记unknown，不把普通席余票或静态£25标签当舞台票。@sohoplace nLiven日历的Low徽标在售罄场次也存在，所以不用它判断有票；官方主页场次计数可能有剧院自身同步/缓存延迟。所有监控都可能漏掉短于检查间隔的退票。演员出席以剧院公告为准。

### JCS实际阻塞（2026-10-21）

在正常Chrome/Xvfb中分别等待16秒与32秒，两次官方日历都返回`We couldn’t verify your browser`（云端日志为ASCII撇号）。未破解验证码、未复制本地cookie或浏览器凭据、未更改指纹规避验证。普通票£25起、舞台票区静态£25标题都不能证明舞台票可买。JCS不加入正式FEEDS，否则它的持续unknown会阻止其他三项续心跳，使后续停跑告警失去区分。只有官方来源在云端真实读取成功后才可启用。2026-10-22本地实测可读取后曾设置JCS本地检查，随后按用户额度顾虑明确暂停；不因此恢复。

## 田馥甄新增与 Golden Boy 移除（2026-11-01）

监控[远大一般贩售页面](https://ticketplus.com.tw/activity/af2bd66d8fe65d78963cbb5bdc85771c)，不监控已截止的另一抽选活动。覆盖台北小巨蛋12月12、13、15、18、19、20日六场，任意公开票价。每轮重新读取官方活动/场次身份及与网页相同的实时session status；只有明确soldout可视为售罄，错误、空列表、身份/日期错配均记unknown。官网静态“立即購買”栏目和公告不构成放票。

onsale对应真实场次购票按钮，先发余票待核实提醒。随后仅查询公开全票与票区状态：排除隐藏、锁定、身障/陪同及资格限定票；在有效销售窗口内，有明确普通库存才发确认。缺少count不能视作0，也不能宣称有票；不登录、不排队、不调用reserve或order。邮件明确台北时间UTC+8与新台币NT$，购票的实名资料及个人资格由用户自行核对。

Golden Boy已从工作流、测试通知选项、私有Google活跃列表移除。保留历史源文件和测试，因为现有Woolf/JCS共用其中的浏览器工具；不再执行Golden Boy查票。

### 田馥甄真实云端阻塞（2026-11-02）

不能把已写好代码或绿色作业称为已启用。真实运行41369774231的公开HTTP请求返回403；普通Chrome直接读取相同公开资料在41370320472得到CloudFront拒绝响应；41370759313改为正常加载完整官方应用，仍未能在35秒内得到六场有效状态。未登录、未复制cookie、未使用代理、未改指纹、未解验证码。当前状态unknown，不能当售罄。

因此田馥甄**未启用**：只保留默认关闭的hebe_probe手动诊断，移出私有Google健康列表，停止自动访问。用户未要求恢复本地Codex监控，仍不创建。Golden Boy已移除。现有Eurotrash、Suranne指定场、Woolf当天、Lear四项已于2026-11-02 01:07:42 UTC实读并验证独立健康心跳；Bush/JCS按原截止或暂停状态处理。Hebe异常提醒已按连续3次失败规则发送一次，它不是放票提醒。

## Eurotrash停止（2026-11-04）

用户要求停止Eurotrash。已从GitHub自动工作流、私有Google健康列表移除，并停用其独立运行入口和专属测试通知选项。本地旧Eurotrash任务维持PAUSED。保留历史记录和其他监控共用库。Suranne指定场、Virginia Woolf伦敦当天和Lear继续；原有其他暂停或结束项目不恢复。
