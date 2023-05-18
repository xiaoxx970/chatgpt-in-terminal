import os
import i18n

def set_lang(lang:str):
    #   获取路径
    package_directory = os.path.dirname(os.path.abspath(__file__))
    locale_directory = os.path.join(package_directory, 'locale')
    i18n.set('locale', lang)
    i18n.load_path.append(locale_directory)
    return i18n.t

def get_lang():
    return i18n.get('locale')

if __name__ == "__main__":
    print(i18n.get('locale'))

    _=set_lang("en")
    print(_('gpt_term.welcome'))

    _=set_lang("zh_CN")
    print(_('gpt_term.welcome'))
