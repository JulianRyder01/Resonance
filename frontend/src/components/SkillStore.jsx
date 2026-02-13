// frontend/src/components/SkillStore.jsx
import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next'; // [修改点] 引入 i18n
import axios from 'axios';
import { 
  Package, 
  Download, 
  Trash2, 
  RefreshCw, 
  Terminal, 
  Code, 
  GitBranch, 
  Folder 
} from 'lucide-react';
import { toast } from 'sonner';

const API_BASE = "http://localhost:8000/api";

export default function SkillStore() {
  const { t } = useTranslation(); // [修改点] 获取翻译函数
  const [skills, setSkills] = useState({ legacy: {}, imported: {} });
  const [loading, setLoading] = useState(false);
  const [importPath, setImportPath] = useState("");
  const [importing, setImporting] = useState(false);

  const fetchSkills = async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API_BASE}/skills/list`);
      setSkills(res.data);
    } catch (err) {
      toast.error(t("skill.failed_to_load_skills"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSkills();
  }, []);

  const handleImport = async () => {
    if (!importPath.trim()) return;
    setImporting(true);
    const toastId = toast.loading(t('skills.learning')); // [修改点] 翻译
    try {
      const res = await axios.post(`${API_BASE}/skills/learn`, { url_or_path: importPath });
      toast.success(t('common.success'), { id: toastId });
      setImportPath("");
      fetchSkills();
    } catch (err) {
      const msg = err.response?.data?.detail || err.message;
      toast.error(t('common.failed') +`${msg}`, { id: toastId, duration: 5000 });
    } finally {
      setImporting(false);
    }
  };

  const handleDelete = async (name) => {
    if (!confirm(t('skills.delete_confirm', { name }))) return; // [修改点] 翻译带参数
    try {
      await axios.delete(`${API_BASE}/skills/${name}`);
      toast.success(`Skill '${name}' deleted`);
      fetchSkills();
    } catch (err) { toast.error(t('common.failed')+`${err}`); }
  };

  return (
    // 增加 h-full overflow-y-auto 确保可滚动
    <div className="p-8 max-w-6xl mx-auto h-full flex flex-col overflow-y-auto">
      <header className="flex justify-between items-end mb-8 shrink-0">
        <div>
          <h1 className="text-3xl font-bold text-slate-800 flex items-center gap-3">
            <Package className="text-primary" /> {t('skills.title')} {/* [修改点] 翻译 */}
          </h1>
          <p className="text-slate-500 mt-1">{t('skills.subtitle')}</p>
        </div>
        <button onClick={fetchSkills} className="p-2 text-slate-400 hover:text-primary transition">
          <RefreshCw size={20} className={loading ? "animate-spin" : ""} />
        </button>
      </header>

      {/* Import Box */}
      <div className="bg-white p-6 rounded-2xl border border-slate-200 shadow-sm mb-8 shrink-0">
        <h2 className="text-sm font-bold text-slate-700 uppercase tracking-wider mb-4 flex items-center gap-2">
          <Download size={16} /> {t('skills.import_title')} {/* [修改点] 翻译 */}
        </h2>
        <div className="flex gap-4">
          <div className="flex-1 relative">
            <input 
              type="text" 
              placeholder={t('skills.placeholder')}
              className="w-full pl-4 pr-4 py-3 bg-slate-50 border border-slate-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition text-sm font-mono"
              value={importPath}
              onChange={(e) => setImportPath(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleImport()}
            />
          </div>
          <button 
            onClick={handleImport}
            disabled={importing || !importPath}
            className="px-6 py-3 bg-primary text-white font-medium rounded-xl hover:bg-primary-hover disabled:opacity-50 disabled:cursor-not-allowed transition shadow-md flex items-center gap-2"
          >
            {importing ? <RefreshCw className="animate-spin" size={18} /> : <Download size={18} />}
            {t('skills.learn_btn')} {/* [修改点] 翻译 */}
          </button>
        </div>
        <p className="text-xs text-slate-400 mt-3 ml-1">
          Supported: Resonance Scripts, Anthropic MCP Skills (skill.yaml), Standard Python Projects (requirements.txt).
        </p>
      </div>

      {/* Skills Grid */}
      <div className="flex-1 pr-2">
        
        {/* Imported Skills */}
        <div className="mb-8">
          <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-4 px-1">Imported Skills (MCP/Python)</h3>
          {Object.keys(skills.imported).length === 0 ? (
            <div className="p-8 text-center border-2 border-dashed border-slate-100 rounded-xl text-slate-300 italic">
              No imported skills yet. Try adding one above.
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {Object.entries(skills.imported).map(([name, data]) => (
                <div key={name} className="bg-white border border-slate-200 rounded-xl p-5 hover:shadow-lg hover:-translate-y-1 transition-all group relative flex flex-col h-full">
                  <div className="flex items-start justify-between mb-3">
                    <div className="p-2 bg-purple-50 text-purple-600 rounded-lg">
                      <Code size={20} />
                    </div>
                    {/* 根据 Source 显示不同 Badge */}
                    {data.source === 'git' || (data.path && data.path.includes('.git')) ? (
                        <div className="flex items-center gap-1 text-[10px] bg-slate-100 px-2 py-1 rounded text-slate-500 font-mono">
                            <GitBranch size={10} /> Git
                        </div>
                    ) : (
                        <div className="flex items-center gap-1 text-[10px] bg-slate-100 px-2 py-1 rounded text-slate-500 font-mono">
                            <Folder size={10} /> Local
                        </div>
                    )}
                  </div>
                  
                  <h4 className="font-bold text-slate-800 text-lg mb-1 truncate" title={name}>{name}</h4>
                  <p className="text-sm text-slate-500 line-clamp-2 mb-4 flex-1">
                    {data.description || "No description provided."}
                  </p>
                  
                  <div className="mt-auto pt-4 border-t border-slate-50 flex justify-between items-center text-xs text-slate-400 font-mono">
                    <span>VENV: Active</span>
                    <button 
                      onClick={() => handleDelete(name)}
                      className="text-slate-300 hover:text-red-500 hover:bg-red-50 p-1.5 rounded transition"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Legacy Scripts */}
        <div>
          <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-4 px-1">Legacy Scripts (Config.yaml)</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {Object.entries(skills.legacy).map(([name, data]) => (
              <div key={name} className="bg-slate-50 border border-slate-200 rounded-xl p-5 opacity-80 hover:opacity-100 transition-all">
                <div className="flex items-center gap-3 mb-3">
                  <div className="p-1.5 bg-slate-200 text-slate-500 rounded-md">
                    <Terminal size={16} />
                  </div>
                  <span className="font-bold text-slate-700 text-sm">{name}</span>
                </div>
                <p className="text-xs text-slate-500 line-clamp-2 mb-2">{data.description}</p>
                <div className="font-mono text-[10px] text-slate-400 truncate bg-white px-2 py-1 rounded border border-slate-100">
                  {data.command}
                </div>
              </div>
            ))}
          </div>
        </div>

      </div>
    </div>
  );
}