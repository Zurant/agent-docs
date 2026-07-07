import { defineConfig } from 'vitepress'
import { withMermaid } from 'vitepress-plugin-mermaid'

export default withMermaid(defineConfig({
  base: '/agent-docs/',
  title: "Career Hub",
  description: "个人简历、面试准备与过程复盘中心",
  themeConfig: {
    nav: [
      { text: '首页', link: '/' },
      // { text: '简历 (Resume)', link: '/resume/' },
      { text: 'Resume', link: '/resume/' },
      // { text: '面试准备 (Prep)', link: '/prep/' },
      { text: 'Prep', link: '/prep/' },
      // { text: '面试复盘 (Retrospectives)', link: '/retrospectives/' }
      { text: 'Retrospectives', link: '/retrospectives/' }
    ],

    sidebar: {
      '/prep/': [
        {
          text: '面试准备体系',
          items: [
            { text: '概览', link: '/prep/' },
            {
              text: 'AI 与 Agent 工程篇',
              items: [
                { text: '综合与概览', link: '/prep/ai-agent' },
                { text: 'Prompt 工程', link: '/prep/prompt-engineering' }
              ]
            },
            { text: 'Java 后端与基建篇', link: '/prep/java-backend' },
            { text: 'JVM 与线上问题排查 (重点)', link: '/prep/jvm-troubleshooting' },
            {
              text: '项目深挖与准备',
              items: [
                { text: '核心项目概览', link: '/prep/projects' },
                { text: 'Log-Sentinel-AI 深度解析', link: '/prep/log-sentinel-ai-deep-dive' }
              ]
            },
            { text: '高阶系统设计篇', link: '/prep/system-design' }
          ]
        }
      ],
      '/retrospectives/': [
        {
          text: '过程复盘',
          items: [
            { text: '概览', link: '/retrospectives/' },
            { text: '爱商在线 0706下午1:30', link: '/retrospectives/aishang-online-0706' }
          ]
        }
      ]
    }
  }
}))
