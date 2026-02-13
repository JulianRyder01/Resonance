import { useTranslation } from 'react-i18next';

// 自定义Hook封装i18n功能
export const useI18n = () => {
  const { t, i18n } = useTranslation();
  
  // 切换语言的方法
  const changeLanguage = (lng) => {
    i18n.changeLanguage(lng);
    localStorage.setItem('language', lng); // 保存用户选择的语言
  };
  
  // 获取当前语言
  const getCurrentLanguage = () => {
    return i18n.language;
  };
  
  return {
    t, // 翻译函数
    currentLanguage: getCurrentLanguage(),
    changeLanguage,
    availableLanguages: ['en', 'zh'] // 可用语言列表
  };
};