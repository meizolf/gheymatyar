import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { MappingsPage } from './pages/MappingsPage'
import { SettingsPage } from './pages/SettingsPage'
import { WizardPage } from './pages/WizardPage'
import { WorkflowProvider } from './workflow/WorkflowContext'
import './components/ui/ui.css'
import './App.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 5_000,
    },
  },
})

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <WorkflowProvider>
        <BrowserRouter>
          <Routes>
            <Route element={<Layout />}>
              <Route index element={<WizardPage />} />
              <Route path="mappings" element={<MappingsPage />} />
              <Route path="settings" element={<SettingsPage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </WorkflowProvider>
    </QueryClientProvider>
  )
}
