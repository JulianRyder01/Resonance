// frontend/src/components/ModelConfig.jsx
import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { Settings, CheckCircle, Cpu, Key, Server, Plus, Edit2, Trash2, X, Save } from 'lucide-react';
import { toast } from 'sonner';

const API_BASE = "http://localhost:8000/api";

export default function ModelConfig() {
  const [config, setConfig] = useState(null);
  const [loading, setLoading] = useState(true);

  // Modal State
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingProfileId, setEditingProfileId] = useState(null);
  const [formData, setFormData] = useState({
    profile_id: '',
    name: '',
    provider: 'openai',
    model: '',
    api_key: '',
    base_url: '',
    temperature: 0.7
  });

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

  // --- Actions ---

  const handleActivate = async (profileId) => {
    try {
      await axios.post(`${API_BASE}/config/active`, { profile_id: profileId });
      toast.success(`Switched to ${profileId}`);
      fetchConfig();
    } catch (err) {
      toast.error("Failed to switch profile");
    }
  };

  const openEditModal = (id, profile) => {
    setEditingProfileId(id);
    setFormData({
      profile_id: id,
      name: profile.name || id,
      provider: profile.provider || 'openai',
      model: profile.model || '',
      api_key: profile.api_key || '',
      base_url: profile.base_url || '',
      temperature: profile.temperature || 0.7
    });
    setIsModalOpen(true);
  };

  const openAddModal = () => {
    setEditingProfileId(null);
    setFormData({
      profile_id: '',
      name: '',
      provider: 'openai',
      model: '',
      api_key: '',
      base_url: 'https://api.openai.com/v1',
      temperature: 0.7
    });
    setIsModalOpen(true);
  };

  const handleDelete = async (id) => {
    if (!confirm(`Delete profile '${id}'?`)) return;
    try {
      await axios.delete(`${API_BASE}/config/profiles/${id}`);
      toast.success("Profile deleted");
      fetchConfig();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Delete failed");
    }
  };

  const handleSave = async () => {
    if (!formData.profile_id || !formData.model || !formData.api_key) {
      toast.error("ID, Model and API Key are required.");
      return;
    }

    try {
      await axios.post(`${API_BASE}/config/profiles/save`, formData);
      toast.success("Profile saved successfully");
      setIsModalOpen(false);
      fetchConfig();
    } catch (err) {
      toast.error("Failed to save profile");
    }
  };

  if (loading) return <div className="p-8 flex items-center justify-center h-full text-slate-400">Loading configuration...</div>;

  return (
    // [修复点] 添加 h-full overflow-y-auto 以支持滚动
    <div className="p-8 max-w-5xl mx-auto h-full overflow-y-auto relative">
      <header className="mb-10 flex justify-between items-end">
        <div>
        <h1 className="text-3xl font-bold text-slate-800 flex items-center gap-3">
          <Settings className="text-primary" /> Model Configuration
        </h1>
        <p className="text-slate-500 mt-2">Manage LLM profiles and select the active brain.</p>
        </div>
        <button 
          onClick={openAddModal}
          className="flex items-center gap-2 px-4 py-2 bg-primary text-white rounded-xl hover:bg-primary-hover shadow-lg shadow-primary/20 transition-all font-medium text-sm"
        >
          <Plus size={18} /> Add Profile
        </button>
      </header>

      <div className="grid gap-6 pb-20">
        {Object.entries(config.profiles).map(([id, profile]) => {
          const isActive = config.active_profile === id;
          return (
            <div 
              key={id} 
              className={`relative bg-white rounded-xl border transition-all duration-300 p-6 flex flex-col md:flex-row items-start justify-between group
                ${isActive 
                  ? 'border-primary shadow-glow ring-1 ring-primary/20' 
                  : 'border-slate-200 hover:border-slate-300 hover:shadow-md'
                }`}
            >
              <div className="space-y-4 flex-1 w-full">
                <div className="flex items-center gap-3">
                  <div className={`p-2 rounded-lg ${isActive ? 'bg-primary text-white' : 'bg-slate-100 text-slate-500'}`}>
                    <Cpu size={24} />
                  </div>
                  <div>
                    <h3 className="text-lg font-bold text-slate-800 flex items-center gap-2">
                        {profile.name || id}
                        {/* ID Badge */}
                        {id !== (profile.name) && <span className="px-1.5 py-0.5 rounded bg-slate-100 text-slate-400 text-[10px] font-mono font-normal">{id}</span>}
                    </h3>
                    <div className="text-xs font-mono text-slate-400 uppercase tracking-wider">{profile.provider} • {profile.model} • Temp: {profile.temperature}</div>
                  </div>
                  {isActive && (
                    <span className="ml-auto md:ml-4 px-3 py-1 bg-green-100 text-green-700 text-xs font-bold rounded-full flex items-center gap-1 shrink-0">
                      <CheckCircle size={12} /> Active
                    </span>
                  )}
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4 bg-slate-50/50 p-4 rounded-lg border border-slate-100">
                  <div className="flex items-center gap-2 text-sm text-slate-600 overflow-hidden">
                    <Server size={14} className="text-slate-400 shrink-0" />
                    <span className="font-mono truncate" title={profile.base_url}>{profile.base_url || "Default URL"}</span>
                  </div>
                  <div className="flex items-center gap-2 text-sm text-slate-600">
                    <Key size={14} className="text-slate-400 shrink-0" />
                    <span className="font-mono">
                      {profile.api_key && profile.api_key.length > 10 
                        ? `${profile.api_key.substring(0, 6)}...${profile.api_key.substring(profile.api_key.length - 4)}` 
                        : "******"}
                    </span>
                  </div>
                </div>
              </div>

              <div className="mt-6 md:mt-0 md:ml-6 flex flex-row md:flex-col items-end gap-3 w-full md:w-auto justify-end">
                {!isActive && (
                  <button 
                    onClick={() => handleActivate(id)}
                    className="px-5 py-2 bg-white border border-slate-300 text-slate-700 font-medium rounded-lg hover:bg-primary hover:text-white hover:border-primary transition shadow-sm w-full md:w-auto"
                  >
                    Activate
                  </button>
                )}
                
                <div className="flex gap-2">
                    <button 
                        onClick={() => openEditModal(id, profile)}
                        className="p-2 text-slate-400 hover:text-blue-500 hover:bg-blue-50 rounded-lg transition"
                        title="Edit"
                    >
                        <Edit2 size={18} />
                    </button>
                    {!isActive && (
                        <button 
                            onClick={() => handleDelete(id)}
                            className="p-2 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition"
                            title="Delete"
                        >
                            <Trash2 size={18} />
                </button>
                    )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
      
      {/* --- Edit/Add Modal --- */}
      {isModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm animate-in fade-in duration-200">
            <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg overflow-hidden border border-slate-200 animate-in zoom-in-95 duration-200">
                <div className="px-6 py-4 border-b border-slate-100 flex justify-between items-center bg-slate-50/50">
                    <h3 className="font-bold text-slate-800 text-lg">
                        {editingProfileId ? 'Edit Profile' : 'New Profile'}
                    </h3>
                    <button onClick={() => setIsModalOpen(false)} className="text-slate-400 hover:text-slate-600 p-1">
                        <X size={20} />
                    </button>
                </div>
                
                <div className="p-6 space-y-4 max-h-[70vh] overflow-y-auto">
                    <div className="grid grid-cols-2 gap-4">
                        <div className="space-y-1">
                            <label className="text-xs font-bold text-slate-500 uppercase">Profile ID (Unique)</label>
                            <input 
                                className="w-full p-2.5 bg-slate-50 border border-slate-200 rounded-lg text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition disabled:opacity-50"
                                value={formData.profile_id}
                                onChange={e => setFormData({...formData, profile_id: e.target.value})}
                                disabled={!!editingProfileId} // ID cannot be changed once created
                                placeholder="my_custom_model"
                            />
                        </div>
                        <div className="space-y-1">
                            <label className="text-xs font-bold text-slate-500 uppercase">Display Name</label>
                            <input 
                                className="w-full p-2.5 bg-slate-50 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition"
                                value={formData.name}
                                onChange={e => setFormData({...formData, name: e.target.value})}
                                placeholder="My GPT-4"
                            />
                        </div>
                    </div>

                    <div className="space-y-1">
                        <label className="text-xs font-bold text-slate-500 uppercase">Provider</label>
                        <select 
                            className="w-full p-2.5 bg-slate-50 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition"
                            value={formData.provider}
                            onChange={e => setFormData({...formData, provider: e.target.value})}
                        >
                            <option value="openai">OpenAI Compatible (GPT/DeepSeek/Qwen)</option>
                            <option value="ollama">Ollama (Local)</option>
                            <option value="azure">Azure OpenAI</option>
                            <option value="anthropic">Anthropic</option>
                        </select>
                    </div>

                    <div className="space-y-1">
                        <label className="text-xs font-bold text-slate-500 uppercase">Base URL</label>
                        <input 
                            className="w-full p-2.5 bg-slate-50 border border-slate-200 rounded-lg text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition"
                            value={formData.base_url}
                            onChange={e => setFormData({...formData, base_url: e.target.value})}
                            placeholder="https://api.openai.com/v1"
                        />
                    </div>

                    <div className="grid grid-cols-3 gap-4">
                        <div className="col-span-2 space-y-1">
                            <label className="text-xs font-bold text-slate-500 uppercase">Model Name</label>
                            <input 
                                className="w-full p-2.5 bg-slate-50 border border-slate-200 rounded-lg text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition"
                                value={formData.model}
                                onChange={e => setFormData({...formData, model: e.target.value})}
                                placeholder="gpt-4o"
                            />
                        </div>
                        <div className="space-y-1">
                            <label className="text-xs font-bold text-slate-500 uppercase">Temperature</label>
                            <input 
                                type="number" step="0.1" min="0" max="2"
                                className="w-full p-2.5 bg-slate-50 border border-slate-200 rounded-lg text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition"
                                value={formData.temperature}
                                onChange={e => setFormData({...formData, temperature: parseFloat(e.target.value)})}
                            />
                        </div>
                    </div>

                    <div className="space-y-1">
                        <label className="text-xs font-bold text-slate-500 uppercase">API Key</label>
                        <input 
                            type="password"
                            className="w-full p-2.5 bg-slate-50 border border-slate-200 rounded-lg text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition"
                            value={formData.api_key}
                            onChange={e => setFormData({...formData, api_key: e.target.value})}
                            placeholder="sk-..."
                        />
                    </div>
                </div>

                <div className="p-4 border-t border-slate-100 flex justify-end gap-3 bg-slate-50/50">
                    <button 
                        onClick={() => setIsModalOpen(false)}
                        className="px-4 py-2 text-slate-500 hover:bg-slate-100 rounded-lg transition text-sm font-medium"
                    >
                        Cancel
                    </button>
                    <button 
                        onClick={handleSave}
                        className="px-6 py-2 bg-primary text-white rounded-lg hover:bg-primary-hover shadow-lg shadow-primary/20 transition flex items-center gap-2 text-sm font-bold"
                    >
                        <Save size={16} /> Save Profile
                    </button>
                </div>
            </div>
      </div>
      )}
    </div>
  );
}