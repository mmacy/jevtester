import '@fontsource-variable/noto-sans/wdth.css'
import '@fontsource-variable/noto-sans-display/wdth.css'
import '@fontsource/noto-sans-mono/400.css'
import './index.css'

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'

import App from './app'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
)
