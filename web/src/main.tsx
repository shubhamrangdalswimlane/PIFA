import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import { initAuth, sessionUser } from './auth/keycloak';
import './styles.css';

const root = createRoot(document.getElementById('root')!);

function Splash({ title, detail, error }: { title: string; detail?: string; error?: boolean }) {
  return (
    <div className="splash">
      <div className={`splash-card${error ? ' splash-error' : ''}`}>
        <div className="brand-name">PIFA</div>
        <h1>{title}</h1>
        {detail && <p>{detail}</p>}
        {error && (
          <button className="btn btn-primary" onClick={() => window.location.reload()}>
            Retry
          </button>
        )}
      </div>
    </div>
  );
}

root.render(<Splash title="Signing in…" />);

initAuth()
  .then(() => {
    root.render(
      <StrictMode>
        <App user={sessionUser()} />
      </StrictMode>,
    );
  })
  .catch((err: unknown) => {
    const detail = err instanceof Error ? err.message : typeof err === 'object' && err && 'error' in err ? String((err as { error: unknown }).error) : String(err ?? 'Unknown error');
    root.render(<Splash title="Sign-in failed" detail={detail} error />);
  });
