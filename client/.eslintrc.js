module.exports = {
  root: true,
  env: {
    browser: true,
    es2021: true,
    node: true
  },
  extends: [
    'eslint:recommended',
    'plugin:vue/vue3-essential'
  ],
  parserOptions: {
    ecmaVersion: 'latest',
    sourceType: 'module',
    parser: '@babel/eslint-parser',
    requireConfigFile: false,
    babelOptions: {
      presets: ['@vue/cli-plugin-babel/preset']
    }
  },
  plugins: [
    'vue'
  ],
  rules: {
    // 自定义规则
    // 生产构建只提示 console.log；error/warn 是正常的错误日志，不应告警
    'no-console': process.env.NODE_ENV === 'production' ? ['warn', { allow: ['error', 'warn'] }] : 'off',
    'no-debugger': process.env.NODE_ENV === 'production' ? 'warn' : 'off',
    'vue/multi-word-component-names': 'off',
    'vue/no-multiple-template-root': 'off',
    'vue/no-v-model-argument': 'off',
    'vue/require-default-prop': 'off',
    'vue/no-unused-vars': 'error',
    'no-unused-vars': 'error',
    'no-undef': 'error',
    'quotes': ['error', 'single'],
    'semi': ['error', 'never'],
    'indent': ['error', 2],
    'comma-dangle': ['error', 'never']
  },
  globals: {
    defineProps: 'readonly',
    defineEmits: 'readonly',
    defineExpose: 'readonly',
    withDefaults: 'readonly'
  }
}
