// frontend/src/components/TaskMonitor.jsx
import React, { useMemo } from 'react';
import { CheckCircle2, Circle, ListTodo, X } from 'lucide-react';

export default function TaskMonitor({ planRaw, onClose }) {
  // 解析 Markdown 列表
  const tasks = useMemo(() => {
    if (!planRaw) return [];
    
    // 匹配 "- [ ] Task" 或 "- [x] Task"
    const regex = /- \[(x|X| )\] (.*)/g;
    const items = [];
    let match;
    
    while ((match = regex.exec(planRaw)) !== null) {
      items.push({
        completed: match[1].toLowerCase() === 'x',
        text: match[2].trim()
      });
    }
    return items;
  }, [planRaw]);

  if (tasks.length === 0) return null;

  const completedCount = tasks.filter(t => t.completed).length;
  const progress = Math.round((completedCount / tasks.length) * 100);

  return (
    <div className="absolute top-20 right-8 w-80 bg-white/95 backdrop-blur-md border border-border rounded-xl shadow-2xl z-50 animate-in slide-in-from-right-10 duration-500 overflow-hidden flex flex-col max-h-[60vh]">
      {/* Header */}
      <div className="bg-slate-50 px-4 py-3 border-b border-slate-100 flex justify-between items-center shrink-0">
        <div className="flex items-center gap-2">
          <ListTodo size={16} className="text-primary" />
          <span className="font-bold text-slate-700 text-sm">Mission Control</span>
        </div>
        <button onClick={onClose} className="text-slate-400 hover:text-red-500 transition">
          <X size={16} />
        </button>
      </div>

      {/* Progress Bar */}
      <div className="h-1 bg-slate-100 w-full shrink-0">
        <div 
          className="h-full bg-primary transition-all duration-700 ease-out" 
          style={{ width: `${progress}%` }} 
        />
      </div>

      {/* Task List */}
      <div className="p-4 overflow-y-auto flex-1 space-y-3">
        {tasks.map((task, idx) => (
          <div key={idx} className={`flex items-start gap-3 text-sm transition-all duration-300 ${task.completed ? 'opacity-50' : 'opacity-100'}`}>
            <div className="mt-0.5 shrink-0 text-primary">
              {task.completed ? <CheckCircle2 size={16} className="fill-primary text-white" /> : <Circle size={16} />}
            </div>
            <span className={`${task.completed ? 'line-through text-slate-400' : 'text-slate-700 font-medium'}`}>
              {task.text}
            </span>
          </div>
        ))}
      </div>

      {/* Footer */}
      <div className="px-4 py-2 bg-slate-50 border-t border-slate-100 text-[10px] text-slate-400 flex justify-between font-mono shrink-0">
        <span>{completedCount}/{tasks.length} DONE</span>
        <span>{progress}%</span>
      </div>
    </div>
  );
}