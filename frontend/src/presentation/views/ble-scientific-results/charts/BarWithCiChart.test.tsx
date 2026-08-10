import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import BarWithCiChart from './BarWithCiChart';
import { BAR_WITH_CI_SYNTHETIC_FIXTURE } from './__fixtures__/chartFixtures';

describe('BarWithCiChart', () => {
  it('renders a bar per category when given real fixture data', () => {
    const { container } = render(<BarWithCiChart data={BAR_WITH_CI_SYNTHETIC_FIXTURE} yLabel="Balanced accuracy" noDataReason="n/a" />);
    expect(container.querySelectorAll('.recharts-bar-rectangle').length).toBe(BAR_WITH_CI_SYNTHETIC_FIXTURE.length);
    expect(screen.getByText('capture-dependent')).toBeInTheDocument();
  });

  it('renders NO DATA and no chart when data is empty', () => {
    render(<BarWithCiChart data={[]} yLabel="Balanced accuracy" noDataReason="no rq1 report yet" />);
    expect(screen.getByText('NO DATA')).toBeInTheDocument();
    expect(screen.getByText('no rq1 report yet')).toBeInTheDocument();
  });

  it('renders NO DATA when data is null', () => {
    render(<BarWithCiChart data={null} yLabel="Balanced accuracy" noDataReason="no rq1 report yet" />);
    expect(screen.getByText('NO DATA')).toBeInTheDocument();
  });
});
