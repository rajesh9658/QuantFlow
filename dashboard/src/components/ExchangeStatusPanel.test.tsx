import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { ExchangeStatusPanel } from './ExchangeStatusPanel';
import { ExchangeStatus } from '../types/dashboard';

const mockExchanges: ExchangeStatus[] = [
  {
    name: 'binance',
    connected: true,
    latency_ms: 32,
    last_heartbeat: '2026-08-20T12:00:00Z',
    symbols_subscribed: ['BTC/USDT', 'ETH/USDT'],
  },
  {
    name: 'coinbase',
    connected: false,
    latency_ms: 0,
    last_heartbeat: '2026-08-20T11:00:00Z',
    symbols_subscribed: ['SOL/USD'],
  },
];

describe('ExchangeStatusPanel Component', () => {
  it('renders exchange cards with online/offline status', () => {
    render(<ExchangeStatusPanel exchanges={mockExchanges} />);

    expect(screen.getByTestId('exchange-card-binance')).toBeInTheDocument();
    expect(screen.getByTestId('exchange-card-coinbase')).toBeInTheDocument();

    expect(screen.getByTestId('exchange-status-binance')).toHaveTextContent('ONLINE');
    expect(screen.getByTestId('exchange-status-coinbase')).toHaveTextContent('DISCONNECTED');

    expect(screen.getByTestId('exchange-latency-binance')).toHaveTextContent('32 ms');
    expect(screen.getByTestId('exchange-latency-coinbase')).toHaveTextContent('N/A');

    expect(screen.getByText('BTC/USDT')).toBeInTheDocument();
    expect(screen.getByText('ETH/USDT')).toBeInTheDocument();
  });
});
