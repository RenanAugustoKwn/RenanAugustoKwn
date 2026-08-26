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

`dark.svg` e `light.svg` são um banner funcional de base. Para substituir o monograma `RA` pelo retrato animado descrito no Master Prompt, ainda são necessários uma foto nítida de rosto e ombros, os três logos de referência e seus dados de localização, formação e portfólio. Mantenha as duas versões para que o `<picture>` continue atendendo os temas claro e escuro.

## Diagnóstico de cache

Para conferir o SVG realmente publicado, abra sua URL em `raw.githubusercontent.com` acrescentando `?v=999`. Em seguida, verifique o tema do GitHub e o último resultado na aba Actions antes de concluir que uma mudança falhou.
