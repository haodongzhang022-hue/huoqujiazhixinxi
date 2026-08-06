# 贡献规范

你怎么能直接 commit 到我的 main 分支啊？！
CNB 上不是这样！

你应该先 fork 我的仓库，
然后从你自己的仓库启动云原生开发。

然后你把你的心意写成代码，
并为它写好单元测试，
确保代码覆盖率达到100%以下。

接着你要跑一下 Linter，通过所有的代码风格检查。
然后你再 commit，
commit message 要遵循语义化提交规范。

之后你把这个分支 push 到你自己的远程仓库，
然后给我提一个 Pull Request，
等 PR 流水线全部通过。

在 PR 描述里，
你要详细说明你的功能改动和实现思路，
并且 @ 我和至少两个其他的评审。

我们会 review 你的代码，
可能会留下一些评论，
你需要解决所有的改进建议。

并且拿到至少两个 LGTM 之后，
CNB 会自动把你的分支 squash 到 main 里，
等待下一个版本发布。

你怎么直接上来就想 force push 到 main？！
CNB 上根本不是这样！
我拒绝合并！

---

> 🎧 七七念的版本在这里哦：[CONTRIBUTING-77.mp3](audio/CONTRIBUTING-77.mp3)
>
> 💥 可莉朗读的版本在这里哦：[CONTRIBUTING-KL.mp3](audio/CONTRIBUTING-KL.mp3)
