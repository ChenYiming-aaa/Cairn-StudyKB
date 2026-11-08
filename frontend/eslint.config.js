import js from '@eslint/js'
import pluginVue from 'eslint-plugin-vue'
import globals from 'globals'

// 只抓正确性问题（未定义变量、未使用变量、Vue 必备规则），不做风格约束。
// 项目风格（无分号、单引号）靠人守，不让 lint 在格式上刷存在感。
export default [
  { ignores: ['dist/**', 'dist-demo/**', 'node_modules/**', 'e2e/**'] },
  js.configs.recommended,
  ...pluginVue.configs['flat/essential'],
  {
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: { ...globals.browser, ...globals.es2021 },
    },
    rules: {
      // Vue 模板里的 ref 会自动解包，no-unused-vars 对模板使用识别不全，交给 vue 插件判断
      'no-unused-vars': ['error', { argsIgnorePattern: '^_', caughtErrors: 'none' }],
    },
  },
  {
    // 视图组件由路由直接挂载，不是可复用组件，不受「多单词命名」约束
    files: ['src/views/**/*.vue'],
    rules: { 'vue/multi-word-component-names': 'off' },
  },
]
