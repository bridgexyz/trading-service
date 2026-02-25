import { Routes, Route } from "react-router-dom";
import { AuthProvider } from "./contexts/AuthContext";
import ProtectedRoute from "./components/ProtectedRoute";
import Layout from "./components/Layout";
import DashboardPage from "./pages/DashboardPage";
import PairsPage from "./pages/PairsPage";
import PairDetailPage from "./pages/PairDetailPage";
import CredentialsPage from "./pages/CredentialsPage";
import LogsPage from "./pages/LogsPage";
import LoginPage from "./pages/LoginPage";

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="*"
          element={
            <ProtectedRoute>
              <Layout>
                <Routes>
                  <Route path="/" element={<DashboardPage />} />
                  <Route path="/pairs" element={<PairsPage />} />
                  <Route path="/pairs/:id" element={<PairDetailPage />} />
                  <Route path="/credentials" element={<CredentialsPage />} />
                  <Route path="/logs" element={<LogsPage />} />
                </Routes>
              </Layout>
            </ProtectedRoute>
          }
        />
      </Routes>
    </AuthProvider>
  );
}
