# 当前PFI论文：MinerU与PyMuPDF实际解析对照

2026-10-29。使用同一份14页PDF，先重跑原PyMuPDF解析器及1200/200固定切块，再调用官方精准解析API。请求model_version=vlm，实际结果报告backend=hybrid、version=3.4.4，不能把官网本地4.x版本当作本次云端版本。

**结果：MinerU提供了更完整的结构化表格、图片资源和页面坐标；本次结果同时出现正文重复、标题误识别和标题层级不准确，尚不宜直接替换当前问答库。**

| 项目 | 原PyMuPDF流程 | 当前规则切块 | 本次MinerU输出 |
| --- | --- | --- | --- |
| 处理单位 | 按页提取文字，1200字符、重叠200字符 | 句末/标题规则与单页表格分组 | 模型识别的结构块 |
| 数量 | 44个检索块 | 81个检索块 | 161个原始结构块，尚未转成RAG检索块 |
| 表格 | 纯文本，表头/数字的行列关系弱 | 2个完整单页表格文本块 | 2个HTML表格，保留跨行/跨列表头 |
| 标题 | 文字中包含标题，原流程不保存章节树 | 部分标题用于切分，没有章节树 | 16个标题候选；含误判、重复，章节和小节都被标成level 2 |
| 图片 | 原问答流程没有提取/索引图片 | 仍为文本问答 | 17个chart块、4个image块、28个图像文件；含子图、表格、公式裁剪及标志 |
| 定位 | 页码、块编号 | 页码、块编号和组成块 | 161个结构块均有page_idx和bbox |

以上对比的是项目实际启用的PyMuPDF用法；PyMuPDF库本身也有提取坐标、图片和表格等其他接口。

## 数值与切块核对

- 原流程本次重跑得到44块，44块文字与原库逐块完全一致。
- 表1在旧固定切块中已经完整落在一个块内；表2跨两个旧块，两块都不单独包含完整表格。当前规则版本将两张表各保存为一个表格块。
- MinerU两张表的20行、每行6个数值（含转数列），共120个单元格，与已核对原表的冻结文本有120个数值一致。
- 这不等于整表或整篇100%准确：表1晶面指数的上划线仍未得到正确保留，表头、脚注、公式和语义不在上述数值一致率内。

## 实际发现的问题

- 第4页：3. Results and Discussions和3.1标题在MinerU文字中各重复两次，原PyMuPDF提取各一次。
- 第5页：The value of the CI-XI在正文中被输出三次，原PyMuPDF提取一次；部分文字混入sup/sub标记。
- 第7页：图片中的4.1 nm被识别成标题。3.2标题混入前一个图注，Conclusions标题也混入前文。
- 摘要中的O(3′)附近出现O(3<sup>0</sup>)形式，科学符号仍需核对。
- 所有非文档标题候选均为level 2，未可靠区分章与节。
- chart块的content为空；当前证明的是提取图像区域，不是可靠提取曲线数值或理解显微图。

## API入口与实施建议

- [官方Token管理](https://mineru.net/apiManage/token)：登录后创建Token。本次已验证用户提供的Token可调用官方精准接口。
- [官方API文档](https://mineru.net/apiManage/docs)：精准API需要Token并提供Markdown/JSON；免Token轻量API主要输出Markdown，不能默认等同于本次精准模式。账号额度和免费条件以控制台为准。
- Token只保存在被Git忽略的backend/.env.mineru。临时上传地址、下载地址、任务响应留在本地私有目录。

本地PyMuPDF提取加固定切块约0.48秒；MinerU从申请上传到结果下载约24.41秒，包含网络与排队，两者计时范围不同。API未返回费用，不能记录为已证实的零费用。

本次没有Embedding、答题或评委调用，没有切换原问答索引。后续应先处理正文重复与标题误判，再建立章节树、结构化分块和页面区域引用；再独立验证问答效果。

[打开并排对照HTML](../data/literature/parsing-comparisons/mineru-vs-pymupdf-20261029/comparison.html)。

## 复现与私有配置

配置样例：[.env.mineru.example](../backend/.env.mineru.example)。复制为backend/.env.mineru后填写Token，实际配置已被Git忽略。

- [本次API提交与恢复脚本](../scripts/parse_mineru_pfi_20261029.py)：submit提交一次，poll查询并下载；已有任务会阻止重复提交，已完成任务的poll直接使用本地结果。
- [原PyMuPDF基线脚本](../scripts/baseline_pymupdf_pfi_20261029.py)：本实验用相邻旧项目srp的Python环境及其解析器/切块代码运行，保留版本和源文件指纹。
- [离线对照报告脚本](../scripts/report_mineru_comparison_20261029.py)：保留私有原始结果后可离线重建；--refresh会先核验既有报告指纹，拒绝覆盖手工修改。

```powershell
.\.venv\Scripts\python.exe scripts\parse_mineru_pfi_20261029.py poll
.\.venv\Scripts\python.exe scripts\report_mineru_comparison_20261029.py --refresh
```
