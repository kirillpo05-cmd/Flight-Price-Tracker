import axios from 'axios'

const client = axios.create({ baseURL: '/api/v1' })

client.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

client.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('token')
      const expired = err.config?.url !== '/auth/login'
      window.location.href = expired ? '/login?session=expired' : '/login'
    }
    return Promise.reject(err)
  },
)

export default client
