<template>
  <div class="auth-shell">
    <!-- 全屏点阵与柔和环境光 -->
    <div class="shell-grid" aria-hidden="true"></div>
    <div class="shell-ambient" aria-hidden="true"></div>

    <!-- 左侧品牌介绍区 -->
    <section class="brand-area">
      <div class="brand-glow" aria-hidden="true"></div>
      <div class="brand-glow brand-glow--top" aria-hidden="true"></div>

      <div class="brand-content">
        <h1 class="brand-title">CodeMind</h1>
        <h2 class="brand-subtitle">AI代码理解与文档生成助手</h2>
        <p class="brand-desc">让代码阅读、注释生成与项目文档整理更高效</p>
        <div class="tag-group">
          <span>智能解析</span>
          <span>自动注释</span>
          <span>文档生成</span>
        </div>

        <!-- 悬浮代码卡片：替代抽象装饰，直接展示产品在做的事 -->
        <div class="brand-preview" aria-hidden="true">
          <div class="preview-head">
            <i class="preview-dot preview-dot--red"></i>
            <i class="preview-dot preview-dot--yellow"></i>
            <i class="preview-dot preview-dot--green"></i>
            <span class="preview-file">utils/math.js</span>
          </div>
          <pre class="preview-code"><span class="tk-comment">/** 计算两个数的和 */</span>
<span class="tk-keyword">export function</span> <span class="tk-fn">add</span>(a, b) {
  <span class="tk-keyword">return</span> a + b
}</pre>
          <div class="preview-badge">
            <i class="preview-badge-dot"></i>
            AI 已补全注释
          </div>
        </div>
      </div>
    </section>

    <!-- 右侧表单区 -->
    <section class="form-area">
      <div class="form-halo" aria-hidden="true"></div>
      <div class="form-card">
        <div class="tab-wrap">
          <div class="tab-item" :class="{ active: active === 'login' }" @click="go('login')">登录</div>
          <div
            v-if="registerEnabled"
            class="tab-item"
            :class="{ active: active === 'register' }"
            @click="go('register')">注册</div>
        </div>
        <slot />
      </div>
    </section>

    <button type="button" class="about-link" @click="openAbout">关于系统</button>
    <p class="shell-footer">CodeMind · 基于 LangChain 与 DeepSeek 的代码理解与文档生成助手</p>
  </div>
</template>

<script>
export default {
  name: 'AuthShell',
  props: {
    // 当前激活的 Tab：login / register
    active: { type: String, default: 'login' },
    // 站点关闭公开注册后隐藏注册 Tab
    registerEnabled: { type: Boolean, default: true }
  },
  methods: {
    go(tab) {
      if (tab === this.active) return
      const query = tab === 'login' && this.$route.query.redirect
        ? { redirect: this.$route.query.redirect }
        : {}
      this.$router.push({ path: tab === 'login' ? '/login' : '/register', query })
    },
    // 登录页不渲染顶栏，这里透出一个入口触发 App 里的关于弹窗
    openAbout() {
      window.dispatchEvent(new CustomEvent('open-about-dialog'))
    }
  }
}
</script>

<!-- 非 scoped：让插槽内的表单元素共用这套浅色主题，选择器统一以 .auth-shell 收口 -->
<style>
.auth-shell {
  position: relative;
  display: flex;
  min-height: 100%;
  overflow: hidden;
  color: #303133;
  background: linear-gradient(135deg, #F5F7FA 0%, #EDF1F8 100%);
}

/* ========== 全屏氛围层 ========== */
.auth-shell .shell-grid {
  position: absolute;
  inset: 0;
  background-image: radial-gradient(rgba(108, 126, 225, 0.16) 1px, transparent 1px);
  background-size: 32px 32px;
  opacity: 0.5;
  pointer-events: none;
}

.auth-shell .shell-ambient {
  position: absolute;
  inset: 0;
  pointer-events: none;
  background:
    radial-gradient(900px 620px at 72% 42%, rgba(108, 126, 225, 0.12), transparent 70%),
    radial-gradient(720px 520px at 96% 92%, rgba(143, 162, 255, 0.12), transparent 70%),
    radial-gradient(520px 420px at 52% 8%, rgba(108, 126, 225, 0.08), transparent 70%);
}

/* ========== 左侧品牌区 ========== */
.auth-shell .brand-area {
  position: relative;
  z-index: 1;
  width: 40%;
  padding: 64px 50px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  overflow: hidden;
  background: linear-gradient(160deg, #FFFFFF 0%, #F4F7FC 100%);
}

/* 两栏之间的竖向分隔 */
.auth-shell .brand-area::after {
  content: '';
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  width: 1px;
  background: linear-gradient(180deg, transparent, rgba(108, 126, 225, 0.35) 35%, rgba(108, 126, 225, 0.2) 65%, transparent);
}

/* 光晕图层比可视区更大，并给每层指定明确半径，避免渐变被图层边界裁出直角 */
.auth-shell .brand-glow {
  position: absolute;
  left: -200px;
  bottom: -200px;
  width: 940px;
  height: 940px;
  pointer-events: none;
  background:
    radial-gradient(420px 420px at 30% 70%, rgba(108, 126, 225, 0.14), transparent 72%),
    radial-gradient(460px 460px at 55% 80%, rgba(168, 123, 255, 0.1), transparent 74%);
  filter: blur(18px);
}

.auth-shell .brand-glow--top {
  left: auto;
  right: -260px;
  bottom: auto;
  top: -320px;
  background:
    radial-gradient(380px 380px at 60% 40%, rgba(143, 162, 255, 0.16), transparent 72%),
    radial-gradient(420px 420px at 40% 60%, rgba(108, 126, 225, 0.1), transparent 74%);
}

.auth-shell .brand-content {
  position: relative;
  z-index: 1;
}

.auth-shell .brand-content::before {
  content: '';
  display: block;
  width: 58px;
  height: 4px;
  margin-bottom: 24px;
  border-radius: 2px;
  background: linear-gradient(90deg, #3730A3, #8FA2FF);
}

.auth-shell .brand-title {
  margin-bottom: 16px;
  font-size: 48px;
  font-weight: 700;
  letter-spacing: 0.5px;
  background: linear-gradient(90deg, #4C5DC6 0%, #6C7EE1 55%, #8FA2FF 100%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}

.auth-shell .brand-subtitle {
  margin-bottom: 18px;
  font-size: 22px;
  font-weight: 600;
  color: #303133;
}

.auth-shell .brand-desc {
  margin-bottom: 28px;
  font-size: 16px;
  line-height: 1.7;
  color: #606266;
}

.auth-shell .tag-group span {
  display: inline-block;
  padding: 6px 14px;
  margin: 0 10px 10px 0;
  font-size: 14px;
  color: #5A6BD0;
  border: 1px solid rgba(108, 126, 225, 0.35);
  border-radius: 99px;
  background: rgba(108, 126, 225, 0.08);
}

/* ========== 悬浮代码卡片 ========== */
.auth-shell .brand-preview {
  position: relative;
  width: 100%;
  max-width: 400px;
  margin-top: 30px;
  border: 1px solid rgba(140, 160, 220, 0.28);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.92);
  box-shadow: 0 18px 40px rgba(31, 45, 97, 0.12), 0 0 40px rgba(108, 126, 225, 0.08);
  animation: brand-float 7s ease-in-out infinite;
}

.auth-shell .preview-head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 14px;
  border-bottom: 1px solid #F0F2F7;
  background: #FAFBFD;
  border-radius: 14px 14px 0 0;
}

.auth-shell .preview-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
}

.auth-shell .preview-dot--red { background: #FF5F57; }
.auth-shell .preview-dot--yellow { background: #FEBC2E; }
.auth-shell .preview-dot--green { background: #28C840; }

.auth-shell .preview-file {
  margin-left: 8px;
  font-size: 12px;
  color: #909399;
}

.auth-shell .preview-code {
  margin: 0;
  padding: 14px 16px;
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 12.5px;
  line-height: 1.8;
  color: #303133;
  white-space: pre;
}

.auth-shell .tk-comment { color: #7A86E8; }
.auth-shell .tk-keyword { color: #B45BC9; }
.auth-shell .tk-fn { color: #2C8BD8; }

.auth-shell .preview-badge {
  position: absolute;
  top: -12px;
  right: 16px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  font-size: 12px;
  color: #2FB874;
  background: #FFFFFF;
  border: 1px solid rgba(53, 201, 127, 0.4);
  border-radius: 99px;
  box-shadow: 0 6px 16px rgba(53, 201, 127, 0.18);
}

.auth-shell .preview-badge-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #35C97F;
}

@keyframes brand-float {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-8px); }
}

@media (prefers-reduced-motion: reduce) {
  .auth-shell .brand-preview {
    animation: none;
  }
}

/* ========== 右侧表单区 ========== */
.auth-shell .form-area {
  position: relative;
  z-index: 1;
  width: 60%;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 48px 20px;
}

/* 卡片背后的柔光，避免卡片悬浮在空旷区域 */
.auth-shell .form-halo {
  position: absolute;
  left: 50%;
  top: 50%;
  width: 660px;
  height: 660px;
  margin: -330px 0 0 -330px;
  border-radius: 50%;
  pointer-events: none;
  background: radial-gradient(circle, rgba(108, 126, 225, 0.16), rgba(108, 126, 225, 0.05) 45%, transparent 70%);
  filter: blur(6px);
}

.auth-shell .form-halo::after {
  content: '';
  position: absolute;
  inset: 130px;
  border: 1px solid rgba(140, 160, 220, 0.22);
  border-radius: 50%;
}

.auth-shell .form-card {
  position: relative;
  width: 440px;
  max-width: 100%;
  padding: 40px;
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.92);
  backdrop-filter: blur(10px);
  box-shadow: 0 20px 50px rgba(31, 45, 97, 0.12), 0 0 50px rgba(108, 126, 225, 0.1);
}

/* 渐变描边 */
.auth-shell .form-card::before {
  content: '';
  position: absolute;
  inset: -1px;
  padding: 1px;
  border-radius: 21px;
  background: linear-gradient(135deg, rgba(108, 126, 225, 0.65), rgba(140, 160, 220, 0.2) 45%, rgba(168, 123, 255, 0.45));
  -webkit-mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
  mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
  -webkit-mask-composite: xor;
  mask-composite: exclude;
  pointer-events: none;
}

/* 顶部高光 */
.auth-shell .form-card::after {
  content: '';
  position: absolute;
  top: 0;
  left: 28px;
  right: 28px;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.9), transparent);
  pointer-events: none;
}

.auth-shell .tab-wrap {
  display: flex;
  margin-bottom: 30px;
  border-bottom: 1px solid rgba(0, 0, 0, 0.07);
}

.auth-shell .tab-item {
  position: relative;
  padding: 10px 0;
  margin-right: 36px;
  font-size: 18px;
  color: #909399;
  cursor: pointer;
  transition: color 0.2s;
}

.auth-shell .tab-item:hover {
  color: #303133;
}

.auth-shell .tab-item.active {
  color: #303133;
  font-weight: 600;
}

.auth-shell .tab-item.active::after {
  content: '';
  position: absolute;
  left: 0;
  bottom: -1px;
  width: 100%;
  height: 2px;
  border-radius: 2px;
  background: #6E7DF0;
  box-shadow: 0 1px 8px rgba(110, 125, 240, 0.5);
}

.auth-shell .auth-heading {
  margin-bottom: 8px;
  font-size: 24px;
  font-weight: 600;
  text-align: center;
  color: #303133;
}

.auth-shell .auth-sub {
  margin-bottom: 28px;
  font-size: 14px;
  text-align: center;
  color: #909399;
}

/* 表单控件 */
.auth-shell .el-form-item {
  margin-bottom: 20px;
}

.auth-shell .el-input__wrapper {
  height: 48px;
  padding: 0 14px;
  border-radius: 10px;
  background: #FFFFFF;
  border: 1px solid rgba(140, 160, 220, 0.35);
  box-shadow: none;
  transition: all 0.2s;
}

.auth-shell .el-input__wrapper:hover {
  border-color: rgba(108, 126, 225, 0.55);
}

.auth-shell .el-input__wrapper.is-focus {
  border-color: #6C7EE1;
  box-shadow: 0 0 0 3px rgba(108, 126, 225, 0.14);
}

.auth-shell .el-input__inner {
  height: 48px;
  color: #303133;
}

.auth-shell .el-input__inner::placeholder {
  color: #A8ABB2;
}

.auth-shell .el-input__prefix,
.auth-shell .el-input__suffix {
  color: #909399;
}

.auth-shell .el-form-item__error {
  color: #F2788B;
}

/* 密码显示/隐藏开关 */
.auth-shell .pwd-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  color: #909399;
  cursor: pointer;
  transition: color 0.2s;
}

.auth-shell .pwd-toggle:hover {
  color: #6C7EE1;
}

.auth-shell .auth-submit {
  width: 100%;
  height: 48px;
  margin-top: 8px;
  border: none;
  border-radius: 10px;
  font-size: 16px;
  font-weight: 500;
  color: #FFFFFF;
  cursor: pointer;
  background: linear-gradient(90deg, #5B6AE5, #8C9BFF);
  box-shadow: 0 8px 20px rgba(91, 106, 229, 0.28);
  transition: opacity 0.2s, transform 0.2s;
}

.auth-shell .auth-submit:hover:not(:disabled) {
  opacity: 0.95;
  transform: translateY(-1px);
}

.auth-shell .auth-submit:disabled {
  opacity: 0.55;
  cursor: not-allowed;
  box-shadow: none;
}

.auth-shell .auth-tip {
  margin-top: 24px;
  font-size: 14px;
  text-align: center;
  color: #909399;
}

.auth-shell .auth-tip .link {
  color: #5A6BD0;
  cursor: pointer;
}

.auth-shell .auth-tip .link:hover {
  text-decoration: underline;
}

.auth-shell .el-alert {
  margin-bottom: 20px;
}

/* ========== 角落元素 ========== */
.auth-shell .about-link {
  position: absolute;
  top: 22px;
  right: 32px;
  z-index: 2;
  padding: 6px 14px;
  font-size: 13px;
  color: #606266;
  background: rgba(255, 255, 255, 0.9);
  border: 1px solid rgba(140, 160, 220, 0.3);
  border-radius: 99px;
  cursor: pointer;
  transition: all 0.2s;
}

.auth-shell .about-link:hover {
  color: #5A6BD0;
  border-color: rgba(108, 126, 225, 0.6);
  background: rgba(108, 126, 225, 0.1);
}

.auth-shell .shell-footer {
  position: absolute;
  right: 40px;
  bottom: 22px;
  z-index: 2;
  font-size: 12px;
  color: #A8ABB2;
}

/* 窄屏改为上下布局 */
@media (max-width: 900px) {
  .auth-shell {
    flex-direction: column;
  }

  .auth-shell .brand-area,
  .auth-shell .form-area {
    width: 100%;
  }

  .auth-shell .brand-area {
    padding: 48px 28px;
  }

  .auth-shell .brand-area::after {
    display: none;
  }

  .auth-shell .brand-title {
    font-size: 34px;
  }

  .auth-shell .brand-subtitle {
    font-size: 18px;
  }

  /* 窄屏空间有限，隐藏装饰卡片与页脚 */
  .auth-shell .brand-preview,
  .auth-shell .shell-footer {
    display: none;
  }

  .auth-shell .form-area {
    padding: 32px 20px 48px;
  }

  .auth-shell .form-card {
    padding: 28px 22px;
  }

  .auth-shell .form-halo {
    width: 420px;
    height: 420px;
    margin: -210px 0 0 -210px;
  }
}
</style>
