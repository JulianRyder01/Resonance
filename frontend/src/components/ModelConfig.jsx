import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { Settings, CheckCircle, Cpu, Key, Server } from 'lucide-react';
import { toast } from 'sonner';

const API_BASE = "http://localhost:8000/api";

export default function ModelConfig() {
  const [config, setConfig] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchConfig = async () => {
    try {
      const res = await axios.get(`${API_BASE}/config`);
      setConfig(res.data);
      setLoading(false);
    } catch (err) {
      toast.error("Failed to load config");
    }
  };

  useEffect(() => {
    fetchConfig();
  }, []);

  const handleActivate = async (profileId) => {
    try {
      await axios.post(`${API_BASE}/config/active`, { profile_id: profileId });
      toast.success(`Switched to ${profileId}`);
      fetchConfig(); // Refresh to update UI
    } catch (err) {
      toast.error("Failed to switch profile");
    }
  };

  if (loading) return <div className="p-8">Loading configuration...</div>;

  return (
    <div className="p-8 max-w-5xl mx-auto">
      <header className="mb-10">
        <h1 className="text-3xl font-bold text-slate-800 flex items-center gap-3">
          <Settings className="text-primary" /> Model Configuration
        </h1>
        <p className="text-slate-500 mt-2">Manage LLM profiles and select the active brain.</p>
      </header>

      <div className="grid gap-6">
        {Object.entries(config.profiles).map(([id, profile]) => {
          const isActive = config.active_profile === id;
          return (
            <div 
              key={id} 
              className={`relative bg-white rounded-xl border transition-all duration-300 p-6 flex items-start justify-between group
                ${isActive 
                  ? 'border-primary shadow-glow ring-1 ring-primary/20' 
                  : 'border-slate-200 hover:border-slate-300 hover:shadow-md'
                }`}
            >
              <div className="space-y-4 flex-1">
                <div className="flex items-center gap-3">
                  <div className={`p-2 rounded-lg ${isActive ? 'bg-primary text-white' : 'bg-slate-100 text-slate-500'}`}>
                    <Cpu size={24} />
                  </div>
                  <div>
                    <h3 className="text-lg font-bold text-slate-800">{profile.name || id}</h3>
                    <div className="text-xs font-mono text-slate-400 uppercase tracking-wider">{profile.provider} • {profile.model}</div>
                  </div>
                  {isActive && (
                    <span className="ml-2 px-3 py-1 bg-green-100 text-green-700 text-xs font-bold rounded-full flex items-center gap-1">
                      <CheckCircle size={12} /> Active
                    </span>
                  )}
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4 bg-slate-50/50 p-4 rounded-lg border border-slate-100">
                  <div className="flex items-center gap-2 text-sm text-slate-600">
                    <Server size={14} className="text-slate-400" />
                    <span className="font-mono truncate max-w-[200px]" title={profile.base_url}>{profile.base_url || "Default URL"}</span>
                  </div>
                  <div className="flex items-center gap-2 text-sm text-slate-600">
                    <Key size={14} className="text-slate-400" />
                    <span className="font-mono">
                      {profile.api_key && profile.api_key.length > 10 
                        ? `${profile.api_key.substring(0, 6)}...${profile.api_key.substring(profile.api_key.length - 4)}` 
                        : "******"}
                    </span>
                  </div>
                </div>
              </div>

              <div className="ml-6 flex flex-col items-end gap-3">
                {!isActive && (
                  <button 
                    onClick={() => handleActivate(id)}
                    className="px-5 py-2 bg-white border border-slate-300 text-slate-700 font-medium rounded-lg hover:bg-primary hover:text-white hover:border-primary transition shadow-sm"
                  >
                    Activate
                  </button>
                )}
                {/* 预留编辑按钮，后端暂时只支持切换 */}
                <button className="text-slate-400 hover:text-primary text-sm font-medium transition" disabled>
                  Edit Profile
                </button>
              </div>
            </div>
          );
        })}
      </div>
      
      <div className="mt-8 p-4 bg-blue-50 border border-blue-100 rounded-lg text-sm text-blue-700 flex items-center gap-3">
        <div className="bg-blue-200 rounded-full p-1"><CheckCircle size={14} /></div>
        To add new profiles, please edit the <code>config/profiles.yaml</code> file directly for security reasons.
      </div>
    </div>
  );
}