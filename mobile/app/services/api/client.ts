import axios from 'axios';
import { useSessionStore } from '../../store/sessionStore';

export const apiClient = axios.create({
  baseURL: 'http://localhost:8888/api/v1',
  timeout: 10000
});

apiClient.interceptors.request.use((config) => {
  const token = useSessionStore.getState().accessToken;
  if (token) {
    config.headers = config.headers ?? {};
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  async (error) => Promise.reject(error)
);
