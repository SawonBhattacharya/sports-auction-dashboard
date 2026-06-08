import os

files = ['ui_components.py', 'views/admin.py', 'views/captain.py', 'views/login.py', 'views/viewer.py']

replacements = {
    "st.markdown('</div>', unsafe_allow_html=True)": "st.html('</div>')",
    "st.markdown('<div class=\"admin-section\">', unsafe_allow_html=True)": "st.html('<div class=\"admin-section\">')",
    "st.markdown('<div class=\"glass-card\">', unsafe_allow_html=True)": "st.html('<div class=\"glass-card\">')",
    "st.markdown('<div class=\"glass-card\" style=\"text-align: center; margin-bottom: 20px;\">', unsafe_allow_html=True)": "st.html('<div class=\"glass-card\" style=\"text-align: center; margin-bottom: 20px;\">')",
    "st.markdown(\"<hr style='border-color: rgba(255,255,255,0.08);'>\", unsafe_allow_html=True)": "st.html(\"<hr style='border-color: rgba(255,255,255,0.08);'>\")"
}

for f in files:
    if not os.path.exists(f): continue
    with open(f, 'r', encoding='utf-8') as file:
        text = file.read()
    
    for old, new in replacements.items():
        text = text.replace(old, new)
        
    with open(f, 'w', encoding='utf-8') as file:
        file.write(text)
print("Done exactly replacing strings!")
