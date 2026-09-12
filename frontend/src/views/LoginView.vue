<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()

const mode = ref<'login' | 'register'>('login')
const loading = ref(false)
const form = reactive({ username: '', password: '' })

async function submit() {
  if (!form.username || !form.password) {
    ElMessage.warning('请填写用户名和密码')
    return
  }
  loading.value = true
  try {
    if (mode.value === 'login') {
      await auth.login(form.username, form.password)
      ElMessage.success('登录成功')
    } else {
      await auth.register(form.username, form.password)
      ElMessage.success('注册成功，已自动登录')
    }
    router.push('/chat')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '操作失败')
  } finally {
    loading.value = false
  }
}

function guest() {
  router.push('/chat')
}
</script>

<template>
  <div class="login-page">
    <div class="card">
      <div class="brand">💊 医疗安全问答系统</div>
      <el-tabs v-model="mode" stretch>
        <el-tab-pane label="登录" name="login" />
        <el-tab-pane label="注册" name="register" />
      </el-tabs>

      <el-form label-position="top" @submit.prevent="submit">
        <el-form-item label="用户名">
          <el-input v-model="form.username" placeholder="3-32 位用户名" />
        </el-form-item>
        <el-form-item :label="mode === 'login' ? '密码' : '密码（≥6 位）'">
          <el-input v-model="form.password" type="password" show-password placeholder="请输入密码" @keyup.enter="submit" />
        </el-form-item>
        <el-button type="primary" size="large" :loading="loading" class="submit" @click="submit">
          {{ mode === 'login' ? '登录' : '注册并登录' }}
        </el-button>
      </el-form>

      <el-divider><span class="divider-text">或</span></el-divider>
      <el-button class="guest-btn" @click="guest">以游客身份进入</el-button>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(160deg, #eef4ff 0%, #f7fbff 100%);
  padding: 24px;
}
.card {
  background: #fff;
  border-radius: 16px;
  box-shadow: 0 16px 48px rgba(23, 101, 255, 0.12);
  padding: 32px 36px;
  width: 400px;
  max-width: 100%;
}
.brand {
  font-size: 18px;
  font-weight: 700;
  text-align: center;
  margin-bottom: 16px;
  color: #1f2d3d;
}
.submit {
  width: 100%;
  margin-top: 4px;
}
.guest-btn {
  width: 100%;
}
.divider-text {
  color: #94a3b8;
  font-size: 12px;
}
</style>