import { BarChart3 } from 'lucide-react';
import { WaterfallView } from '../../../presentation/views/WaterfallView';
import { LabModuleDefinition } from '../types';

export const waterfallModule: LabModuleDefinition = { id: 'waterfall', name: 'Waterfall', path: '/waterfall', icon: BarChart3, element: <WaterfallView />, enabled: true, showInNavigation: true, order: 100, description: 'Waterfall visualization module for spectrum history.' };
