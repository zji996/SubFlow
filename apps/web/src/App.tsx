import { Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/layout/Layout'
import ProjectsPage from './pages/ProjectsPage'
import NewProjectPage from './pages/NewProjectPage'
import ProjectDetailPage from './pages/ProjectDetailPage'
import PreviewPage from './pages/PreviewPage'

function App() {
    return (
        <Routes>
            <Route path="/" element={<Layout />}>
                <Route index element={<Navigate to="/projects" replace />} />
                <Route path="projects" element={<ProjectsPage />} />
                <Route path="projects/new" element={<NewProjectPage />} />
                <Route path="projects/:projectId" element={<ProjectDetailPage />} />
                <Route path="projects/:projectId/preview" element={<PreviewPage />} />
            </Route>
        </Routes>
    )
}

export default App
