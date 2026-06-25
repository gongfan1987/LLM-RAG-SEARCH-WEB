import os
from docx2markdown import docx_to_markdown

# docx 文件路径
docx = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Doc21.docx')

# markdown 文件输出路径
output = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Doc21.md')

# 开始转换
docx_to_markdown(docx, output)