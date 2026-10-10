const { defineConfig } = require('@vue/cli-service')

module.exports = defineConfig({
  transpileDependencies: true,
  // 生产构建不输出 source map，避免前端源码通过 .map 文件被还原
  productionSourceMap: false,
  devServer: {
    port: 8080,
    proxy: {
      '/api': {
        target: 'http://localhost:3001',
        changeOrigin: true,
        secure: false
      }
    }
  },
  configureWebpack: {
    // 仅本地开发保留 source map 便于调试，生产环境关闭
    devtool: process.env.NODE_ENV === 'development' ? 'source-map' : false
  }
})
