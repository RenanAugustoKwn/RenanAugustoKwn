# Conclusão da configuração do perfil

## 1. Habilitar a publicação da cobra

No repositório, acesse **Settings → Actions → General → Workflow permissions** e selecione **Read and write permissions**. Em seguida, faça push desta alteração ou execute manualmente **Generate Snake Animation** na aba Actions. A primeira execução cria a branch `output` e os dois SVGs usados no README.

## 2. Adicionar as estatísticas privadas

1. Crie um token clássico do GitHub com escopo `repo` e guarde-o apenas no Vercel.
2. Faça fork de `anuraghazra/github-readme-stats`.
3. Importe o fork no Vercel e defina a variável de ambiente `PAT_1` com o token.
4. Depois do deploy, substitua `YOUR-INSTANCE` abaixo pelo domínio da sua instância e remova o comentário do bloco.

```html
<div align="center">
  <img width="49%" src="https://YOUR-INSTANCE.vercel.app/api?username=RenanAugustoKwn&show_icons=true&count_private=true&include_all_commits=true&hide_rank=true&hide_border=true&title_color=22D3EE&icon_color=A78BFA&text_color=94A3B8&bg_color=0A101F&card_width=500" alt="Estatísticas do GitHub" />
  <img width="49%" src="https://YOUR-INSTANCE.vercel.app/api/top-langs/?username=RenanAugustoKwn&layout=compact&langs_count=8&hide_border=true&title_color=22D3EE&text_color=94A3B8&bg_color=0A101F&card_width=500" alt="Linguagens mais usadas" />
</div>
```

Não envie o token, nem o adicione a um arquivo local do repositório.

## 3. Personalizar o banner

O banner já possui quatro entregáveis complementares:

- `dark.svg` e `light.svg`: versões estáticas, acessíveis e usadas quando a pessoa prefere menos movimento.
- `visual-map-dark.gif` e `visual-map-light.gif`: o `VISUAL.MAP` animado, usado no README. O GitHub não reproduz animações embutidas em SVG.
- `assets/profile/portrait-dither-reference.png`: referência 1-bit do retrato, usada somente para gerar os paths locais; o SVG publicado não incorpora imagens externas.

Para regenerar os quatro banners após atualizar dados confirmados do perfil ou a referência de retrato, execute:

```powershell
python tools/generate_profile_assets.py
python -m unittest discover -s tests -v
```

O banner exibe somente fatos públicos confirmados. Campos sem confirmação — como origem, formação, portfólio ou links sociais — são omitidos em vez de receber texto de preenchimento. As URLs do README carregam uma versão `?v=20260825` para reduzir problemas de cache após o próximo push.

## Diagnóstico de cache

Para conferir o SVG realmente publicado, abra sua URL em `raw.githubusercontent.com` acrescentando `?v=999`. Em seguida, verifique o tema do GitHub e o último resultado na aba Actions antes de concluir que uma mudança falhou.
