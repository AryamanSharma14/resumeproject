import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { describe, it, expect, vi } from 'vitest';
import { App } from '../App';
import { Jobs } from '../Jobs';
import { JobDetail } from '../JobDetail';
import { Queues } from '../Operations';
import { Submit, payloadFor } from '../Submit';
import { Confirm, QueryState } from '../ui';
import { useApi } from '../api';
import type { Job } from '../types';

const queue = { name: 'default', paused: false, created_at: '2026-01-01T00:00:00Z', due_depth: 0, oldest_due_age_ms: null };
const handlers = { items: [
  { name: 'text_summary', version: '1', description: 'Count text', payload_schema: {} },
  { name: 'batch_statistics', version: '1', description: 'Statistics', payload_schema: {} },
] };
const overview = { as_of: '2026-01-01T00:00:00Z', window: 'retained', jobs: { queued: 0, running: 0, retry_wait: 0, failed: 0 }, queues: [], workers: {} };

function makeJob(overrides: Partial<Job> = {}): Job {
  return { id: 'job-1', handler: 'text_summary', handler_version: '1', queue: 'default', payload: { text: 'x' }, state: 'queued', priority: 0, created_at: '2026-01-01T00:00:01Z', updated_at: '2026-01-01T00:00:01Z', available_at: '2026-01-01T00:00:01Z', started_at: null, finished_at: null, attempt_count: 0, max_attempts: 3, timeout_ms: 30000, active_attempt_id: null, lease_expires_at: null, result: null, last_error_code: null, last_error_summary: null, rerun_of: null, ...overrides };
}

function mount(ui: React.ReactNode, entry = '/jobs') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, refetchInterval: false }, mutations: { retry: false } } });
  const result = render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[entry]}>{ui}</MemoryRouter></QueryClientProvider>);
  return { ...result, client };
}

function respond(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } });
}

function network() {
  return vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
    const path = String(input);
    if (path.includes('/handlers')) return respond(handlers);
    if (path.includes('/queues')) return respond({ items: [queue] });
    if (path.includes('/overview')) return respond(overview);
    return respond({ items: [], next_cursor: null });
  });
}

function Location() {
  return <output aria-label="Current URL">{useLocation().search}</output>;
}

describe('dashboard interactions', () => {
  it('authenticates without persisting the token and disconnects', async () => {
    const fetchMock = network();
    const user = userEvent.setup();
    mount(<App />);
    await user.type(screen.getByLabelText('Installation access token'), 'test-only-secret');
    await user.click(screen.getByRole('button', { name: 'Connect to Relay' }));
    await screen.findByRole('heading', { name: 'Jobs' });
    expect(fetchMock.mock.calls[0][1]?.headers).toMatchObject({ Authorization: 'Bearer test-only-secret' });
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
    await user.click(screen.getByRole('button', { name: 'Disconnect' }));
    expect(screen.getByLabelText('Installation access token')).toHaveValue('');
  });

  it('reports a rejected local token', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(respond({ error: { code: 'UNAUTHORIZED', message: 'Unauthorized' } }, 401));
    const user = userEvent.setup();
    mount(<App />);
    await user.type(screen.getByLabelText('Installation access token'), 'wrong');
    await user.click(screen.getByRole('button', { name: 'Connect to Relay' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Access token rejected');
  });

  it('syncs state filters and resets them in the URL', async () => {
    network();
    const user = userEvent.setup();
    mount(<><Jobs /><Location /></>);
    await screen.findByRole('table');
    await user.selectOptions(screen.getByLabelText('State'), 'failed');
    expect(screen.getByLabelText('Current URL')).toHaveTextContent('state=failed');
    expect(await screen.findByText('No jobs match these filters')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Reset filters' }));
    expect(screen.getByLabelText('Current URL')).toHaveTextContent('');
  });

  it('restores dialog trigger focus on Escape and confirms once', async () => {
    const user = userEvent.setup();
    const action = vi.fn().mockResolvedValue(undefined);
    mount(<Confirm label="Cancel" title="Cancel pending job?" onConfirm={action}>Only pending work.</Confirm>);
    const trigger = screen.getByRole('button', { name: 'Cancel' });
    await user.click(trigger);
    expect(screen.getByRole('dialog')).toHaveTextContent('Only pending work.');
    await user.keyboard('{Escape}');
    await waitFor(() => expect(trigger).toHaveFocus());
    expect(action).not.toHaveBeenCalled();
    await user.click(trigger);
    await user.click(screen.getByRole('button', { name: 'Confirm cancel' }));
    await waitFor(() => expect(action).toHaveBeenCalledTimes(1));
  });
});

describe('detail, staleness and validation', () => {
  it('renders the attempt timeline with retry delay and lost-ownership context', async () => {
    const job = makeJob({ state: 'retry_wait', last_error_summary: 'demo_flaky induced failure on attempt 1' });
    const attempts = { items: [
      { id: 'a1', job_id: 'job-1', number: 1, worker_id: 'worker-x', state: 'failed', started_at: '2026-01-01T00:00:01Z', finished_at: '2026-01-01T00:00:02Z', lease_expires_at: '2026-01-01T00:00:31Z', error_code: 'HANDLER_ERROR', error_summary: 'demo_flaky induced failure on attempt 1', result: null },
      { id: 'a2', job_id: 'job-1', number: 2, worker_id: 'worker-x', state: 'lost', started_at: '2026-01-01T00:00:09Z', finished_at: null, lease_expires_at: '2026-01-01T00:00:39Z', error_code: 'LEASE_LOST', error_summary: 'ownership expired before completion', result: null },
    ], next_cursor: null };
    vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
      const path = String(input);
      if (path.includes('/attempts')) return respond(attempts);
      if (path.includes('/events')) return respond({ items: [], next_cursor: null });
      if (path.includes('/handlers')) return respond(handlers);
      if (path.includes('/overview')) return respond(overview);
      return respond(job);
    });
    mount(<JobDetail />, '/jobs/job-1');
    expect(await screen.findByRole('heading', { name: 'Attempt 1' })).toBeInTheDocument();
    expect(await screen.findByText('Retry delay: 7.0 s')).toBeInTheDocument();
    expect(screen.getAllByText(/Ownership lost/)[0]).toBeInTheDocument();
    expect(screen.getAllByText(/demo_flaky induced failure/)[0]).toBeInTheDocument();
  });

  it('shows not-found for an unknown job ID and returns to jobs', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
      if (String(input).includes('/overview')) return respond(overview);
      return new Response(JSON.stringify({ error: { code: 'JOB_NOT_FOUND', message: 'No such job' } }), { status: 404 });
    });
    const user = userEvent.setup();
    mount(<Routes><Route path="/jobs/:id" element={<JobDetail/>}/><Route path="/jobs" element={<Jobs/>}/></Routes>, '/jobs/nope');
    expect(await screen.findByRole('alert')).toHaveTextContent('No such job');
    await user.click(screen.getByRole('link', { name: '← Back to jobs' }));
    expect(await screen.findByRole('heading', { name: 'Jobs' })).toBeInTheDocument();
  });

  it('keeps first-page ordering during background refresh', async () => {
    const fetchMock = network();
    const { client } = mount(<><Jobs /><Location /></>);
    await screen.findByRole('table');
    fetchMock.mockImplementation(async input => {
      const path = String(input);
      if (path.includes('/overview')) return respond(overview);
      if (path.includes('/handlers')) return respond(handlers);
      if (path.includes('/queues')) return respond({ items: [queue] });
      return respond({ items: [makeJob({ id: 'b', handler: 'batch_statistics', created_at: '2026-01-01T00:00:02Z', updated_at: '2026-01-01T00:00:02Z' }), makeJob({ id: 'a', created_at: '2026-01-01T00:00:01Z' })], next_cursor: null });
    });
    await client.invalidateQueries();
    await waitFor(() => expect(screen.getByText('batch_statistics')).toBeInTheDocument(), { timeout: 3000 });
    const cells = screen.getAllByRole('cell', { name: /batch_statistics|text_summary/ });
    expect(cells[0]).toHaveTextContent('batch_statistics');
  });

  it('retains cached data and disables queue mutation after an outage', async () => {
    const fetchMock = network();
    const { client } = mount(<Queues />);
    await screen.findByRole('button', { name: 'Pause' });
    fetchMock.mockRejectedValue(new TypeError('offline'));
    await client.invalidateQueries();
    expect(await screen.findByText('Stale cached data')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Pause' })).toBeDisabled();
    expect(screen.getByRole('heading', { name: 'default' })).toBeInTheDocument();
  });

  it('validates batch input before posting', async () => {
    const fetchMock = network();
    const user = userEvent.setup();
    mount(<Submit />);
    await screen.findByLabelText('Handler');
    await user.selectOptions(screen.getByLabelText('Handler'), 'batch_statistics');
    await user.type(screen.getByLabelText('Numbers (JSON array)'), 'not-json');
    await user.click(screen.getByRole('button', { name: 'Submit job' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('JSON array');
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false);
  });

  it('shows first-load failure with retry, not fabricated values', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('offline'));
    function View() {
      const query = useApi<unknown>('/overview', false);
      return <QueryState query={query}>{() => <p>Loaded</p>}</QueryState>;
    }
    mount(<View />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Cannot reach Relay');
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
  });

  it('enforces finite lists and bounded integers', () => {
    expect(payloadFor('batch_statistics', '[1,2]')).toEqual({ numbers: [1, 2] });
    expect(() => payloadFor('batch_statistics', '[1e999]')).toThrow('finite');
    expect(() => payloadFor('demo_flaky', '6')).toThrow();
    expect(() => payloadFor('demo_delay', '1.5')).toThrow();
    expect(payloadFor('text_summary', '')).toEqual({ text: '' });
  });
});
