alpha :: Int -> Int
alpha value = value
beta :: Int -> Int
beta value = value
run = do
  print (alpha 1)
  print (alpha (1 + 2))
  print (beta 4)
