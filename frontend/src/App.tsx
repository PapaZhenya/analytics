import { useEffect, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { LoginPage } from "@/pages/LoginPage";
import { CallListPage } from "@/pages/CallListPage";
import { UploadPage } from "@/pages/UploadPage";
import { CallReviewPage } from "@/pages/CallReviewPage";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { useAuthStore } from "@/auth/useAuthStore";
import { fetchCurrentUser, refresh } from "@/api/auth";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

function SessionBootstrap({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = useState(false);
  const setSession = useAuthStore((s) => s.setSession);

  useEffect(() => {
    // The access token lives only in memory, so a hard reload needs to silently trade
    // the httpOnly refresh cookie for a new one before the app can call any protected
    // endpoint.
    (async () => {
      try {
        const { access_token } = await refresh();
        useAuthStore.getState().setAccessToken(access_token);
        const user = await fetchCurrentUser();
        setSession(access_token, user);
      } catch {
        // No valid refresh cookie — user needs to log in, which is the normal case.
      } finally {
        setReady(true);
      }
    })();
  }, [setSession]);

  if (!ready) return <p>Loading...</p>;
  return <>{children}</>;
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <SessionBootstrap>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route
              path="/calls"
              element={
                <ProtectedRoute>
                  <CallListPage />
                </ProtectedRoute>
              }
            />
            <Route
              path="/upload"
              element={
                <ProtectedRoute>
                  <UploadPage />
                </ProtectedRoute>
              }
            />
            <Route
              path="/calls/:callId"
              element={
                <ProtectedRoute>
                  <CallReviewPage />
                </ProtectedRoute>
              }
            />
            <Route path="*" element={<Navigate to="/calls" replace />} />
          </Routes>
        </SessionBootstrap>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
