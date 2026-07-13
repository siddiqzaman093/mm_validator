import { createContext, useContext, useState, useCallback } from 'react'
import { login as apiLogin, setToken, clearToken } from '../api'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [name, setName] = useState(null)
  const [role, setRole] = useState(null)
  const [error, setError] = useState('')

  const login = useCallback(async (username, password) => {
    setError('')
    try {
      const data = await apiLogin(username, password)
      setToken(data.access_token)
      setUser(data.username || username)
      setName(data.name || '')
      setRole(data.role || 'user')
      return true
    } catch (err) {
      const msg = err?.response?.data?.detail || 'Login failed. Check your credentials.'
      setError(msg)
      return false
    }
  }, [])

  const logout = useCallback(() => {
    clearToken()
    setUser(null)
    setName(null)
    setRole(null)
    setError('')
  }, [])

  return (
    <AuthContext.Provider value={{ user, name, role, error, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
