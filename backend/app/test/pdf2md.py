import aspose.words as aw
import os

pdf = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sample.pdf')
save_md = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sample.md')
doc = aw.Document(pdf)
doc.save(save_md)
